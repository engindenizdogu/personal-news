"""Offline tests for pnews.enrich: the model is faked, no API calls."""

import json
from pathlib import Path

import pytest

from pnews import enrich

ALIASES = {"us": "United States", "usa": "United States", "united states": "United States"}
ITEM = {"item_id": "i1", "source_id": "src", "title": "OpenAI and Stripe launch a payments tool", "summary": "Short summary."}
TEXT = "Sam Altman said OpenAI Inc. will work with Stripe in the U.S. on Instant Checkout. The status page was updated."


def answer(entities):
    return json.dumps({"entities": entities})


# ---------------------------------------------------------------- prompt file


def test_prompt_file_splits_and_renders():
    system, user = enrich.load_prompt(Path("prompts/entities_v1.md"))
    assert "organization" in system and "<!--" not in system
    rendered = enrich.render_user(user, "Feed", "A {title}", "text with {braces}")
    assert "A {title}" in rendered and "{braces}" in rendered and "Source: Feed" in rendered


# ---------------------------------------------------------------- parsing and schema


def test_parse_json_tolerates_fences_and_chatter():
    assert enrich.parse_json('```json\n{"entities": []}\n```') == {"entities": []}
    assert enrich.parse_json('Here you go: {"entities": []} done') == {"entities": []}
    with pytest.raises(ValueError):
        enrich.parse_json("no json here")


def test_schema_errors():
    assert enrich.schema_errors({"entities": [{"name": "X", "type": "person", "mention": "X"}]}) == []
    assert enrich.schema_errors({"entities": "nope"}) == ['"entities" must be a list']
    errs = enrich.schema_errors({"entities": [{"name": "X", "type": "event", "mention": ""}]})
    assert any("type 'event'" in e for e in errs) and any("mention" in e for e in errs)


# ---------------------------------------------------------------- grounding and normalization


def test_mention_must_appear_as_whole_word():
    folded = enrich._fold(TEXT)
    assert enrich.mention_in_text("U.S.", folded)
    assert enrich.mention_in_text("openai inc.", folded)  # case-insensitive
    assert not enrich.mention_in_text("US", folded)  # "status" must not count
    assert not enrich.mention_in_text("Gemini", folded)


def test_ground_and_normalize_drops_ungrounded_and_merges():
    ents = [
        {"name": "OpenAI", "type": "organization", "mention": "OpenAI Inc."},
        {"name": "OpenAI Inc.", "type": "organization", "mention": "OpenAI"},  # same entity again
        {"name": "United States", "type": "location", "mention": "U.S."},
        {"name": "Google", "type": "organization", "mention": "Google"},  # not in the text
        {"name": "Instant Checkout", "type": "product", "mention": "Instant Checkout"},
    ]
    kept, dropped = enrich.ground_and_normalize(ents, ITEM["title"], TEXT, ALIASES)
    assert [e["entity_id"] for e in kept] == ["organization:openai", "location:united states", "product:instant checkout"]
    assert [d["name"] for d in dropped] == ["Google"]


def test_entity_key_unifies_dashes_and_keeps_version_numbers():
    nb = enrich.entity_key("product", "GPT‑5.5", {})[0]  # non-breaking hyphen, as on openai.com
    assert nb == enrich.entity_key("product", "GPT-5.5", {})[0] == "product:gpt-5.5"
    assert enrich.entity_key("product", "GPT-5.5", {})[0] != enrich.entity_key("product", "GPT-55", {})[0]
    assert enrich.entity_key("location", "U.S.", {"us": "United States"})[1] == "United States"
    # Grounding accepts an ASCII-hyphen mention when the text uses the typographic one.
    assert enrich.mention_in_text("GPT-6 Cyber", enrich._fold("Introducing GPT‑6 Cyber today"))


def test_entity_key_aliases_and_suffixes():
    assert enrich.entity_key("location", "USA", ALIASES) == ("location:united states", "United States")
    assert enrich.entity_key("organization", "Stripe, Inc.", {})[0] == "organization:stripe"
    assert enrich.entity_key("product", "Co", {})[0] == "product:co"  # suffix rule only for organizations


# ---------------------------------------------------------------- input selection


def test_build_input_prefers_article_then_summary_and_truncates():
    inp = enrich.build_input(ITEM, {"text": "one two  three four"}, max_words=3)
    assert (inp["text"], inp["text_source"], inp["truncated"], inp["input_words"]) == ("one two three", "article", True, 3)
    assert enrich.build_input(ITEM, {"text": None}, 100)["text_source"] == "summary"
    assert enrich.build_input({**ITEM, "summary": ""}, None, 100)["text_source"] == "title_only"


def test_payload_sends_reasoning_routing_and_reads_finish_reason(monkeypatch):
    sent = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"model": "m", "provider": "p", "usage": {},
                               "choices": [{"finish_reason": "stop", "message": {"content": '{"entities": []}'}}]}).encode()

    def fake_urlopen(req, timeout=None):
        sent.update(json.loads(req.data))
        return Resp()

    monkeypatch.setattr(enrich.urllib.request, "urlopen", fake_urlopen)
    cfg = {"api_url": "https://x", "model": "m", "temperature": 0, "seed": 1, "max_tokens": 8000, "json_mode": True,
           "reasoning": {"effort": "low"}, "routing": {"require_parameters": True}}
    out = enrich.call_openrouter(cfg, [{"role": "user", "content": "x"}], "key", enrich.RateLimiter(0))
    assert sent["reasoning"] == {"effort": "low"} and sent["provider"] == {"require_parameters": True}
    assert sent["response_format"] == {"type": "json_object"} and sent["seed"] == 1
    assert out["finish_reason"] == "stop"


def test_cut_off_answer_is_recorded_as_error():
    row = _row([{"content": "", "finish_reason": "length"}, {"content": answer([]), "finish_reason": "stop"}])
    out = enrich.derive_output(ITEM, _inp(), row, ALIASES)
    assert out["status"] == "ok" and out["attempt_used"] == 2
    assert any("finish_reason=length" in e for e in out["errors"][0]["errors"])


def test_input_hash_changes_with_model_and_prompt():
    cfg = {"model": "m", "prompt_version": "v1", "temperature": 0, "seed": 1, "max_tokens": 10, "json_mode": True}
    msgs = [{"role": "user", "content": "x"}]
    h = enrich.input_hash(cfg, msgs)
    assert h == enrich.input_hash(dict(cfg), list(msgs))
    assert h != enrich.input_hash({**cfg, "model": "other"}, msgs)
    assert h != enrich.input_hash({**cfg, "prompt_version": "v2"}, msgs)
    assert h != enrich.input_hash({**cfg, "reasoning": {"effort": "low"}}, msgs)


# ---------------------------------------------------------------- retry and fallback


def _row(attempts):
    return {"input_hash": "h", "model": "m", "prompt_version": "v1", "attempts": attempts}


def _inp():
    return enrich.build_input(ITEM, {"text": TEXT}, 1500)


def test_retry_once_then_ok():
    replies = iter(["not json", answer([{"name": "Stripe", "type": "organization", "mention": "Stripe"}])])
    calls = []
    attempts = enrich.request_with_retry({}, [{"role": "user", "content": "x"}],
                                         lambda m: calls.append(m) or {"content": next(replies)})
    assert len(attempts) == 2 and attempts[1]["retry"] is True
    assert "not valid" in calls[1][-1]["content"]  # the retry shows the error
    out = enrich.derive_output(ITEM, _inp(), _row(attempts), ALIASES)
    assert out["status"] == "ok" and out["attempt_used"] == 2
    assert [e["entity_id"] for e in out["entities"]] == ["organization:stripe"]


def test_no_retry_when_first_answer_valid():
    attempts = enrich.request_with_retry({}, [], lambda m: {"content": answer([])})
    assert len(attempts) == 1


def test_two_invalid_answers_fall_back_to_no_entities():
    attempts = enrich.request_with_retry({}, [], lambda m: {"content": '{"entities": [{"type": "event"}]}'})
    out = enrich.derive_output(ITEM, _inp(), _row(attempts), ALIASES)
    assert out["status"] == "fallback" and out["entities"] == [] and len(out["errors"]) == 2


# ---------------------------------------------------------------- end to end with cache


def test_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=from-file\n")
    assert enrich.get_api_key(env) == "from-file"


def test_environment_variable_wins_over_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=from-file\n")
    assert enrich.get_api_key(env) == "from-env"


def test_missing_key_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=\n")
    assert enrich.get_api_key(env) is None


def test_run_uses_cache_on_second_run(tmp_path, monkeypatch):
    (tmp_path / "feeds.yml").write_text('feeds:\n  - {id: src, name: Src, url: "https://e.com/feed"}\n')
    (tmp_path / "items.jsonl").write_text(json.dumps({**ITEM, "url": "https://e.com/a"}) + "\n")
    (tmp_path / "content.jsonl").write_text(json.dumps({"item_id": "i1", "status": "ok", "text": TEXT}) + "\n")
    cfg = Path("config/enrich.yml").read_text()
    (tmp_path / "enrich.yml").write_text(cfg)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = []

    def fake_call(cfg, messages, api_key, limiter):
        calls.append(messages)
        return {"content": answer([{"name": "Sam Altman", "type": "person", "mention": "Sam Altman"}]),
                "model": cfg["model"], "provider": "fake", "usage": None}

    monkeypatch.setattr(enrich, "call_openrouter", fake_call)
    argv = ["--config", str(tmp_path / "enrich.yml"), "--feeds", str(tmp_path / "feeds.yml"),
            "--aliases", str(tmp_path / "none.yml"), "--items", str(tmp_path / "items.jsonl"),
            "--content", str(tmp_path / "content.jsonl"), "--cache", str(tmp_path / "cache.jsonl"),
            "--out", str(tmp_path / "entities.jsonl"), "--env-file", str(tmp_path / "none.env")]
    enrich.main(argv)
    enrich.main(argv)  # second run: everything cached
    assert len(calls) == 1
    rows = [json.loads(l) for l in (tmp_path / "entities.jsonl").read_text().splitlines()]
    assert rows[0]["item_id"] == "i1" and rows[0]["entities"][0]["entity_id"] == "person:sam altman"
    assert rows[0]["prompt_version"] == "entities_v1"
