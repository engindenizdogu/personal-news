"""LLM enrichment, step 1: named entities per item, via OpenRouter.

For each selected item, build the model input (title + article text, cut to
max_input_words), call the model once per distinct input, and validate the answer
in code before anything uses it:

1. Parse: JSON, tolerating code fences or text around the object.
2. Schema: {"entities": [{"name", "type", "mention"}]}, type from the closed list.
   On failure, one retry that shows the model its error; then fall back to no entities.
3. Grounding: each entity's `mention` must appear in the input text, otherwise the
   entity is dropped (and recorded in `dropped`).
4. Normalization: canonical key per entity (`entity_id`), merging case, company
   suffixes and the aliases in config/entity_aliases.yml. Duplicates are merged.

Caching (reproducibility): every API answer is stored raw in data/enrichment/cache.jsonl,
keyed by a hash of (model, prompt version, settings, exact messages). A cached input is
never sent again. Steps 1-4 always re-run on the cached raw answers, so changing the
checks or the alias table needs no new API calls.

Output: data/enrichment/entities.jsonl, rebuilt on every run from the cache, one row
per selected item that has a cached answer, keyed by `item_id`.

Which items: those with a record in data/content.jsonl (any status). If an item has no
article text, its feed summary is used instead (`text_source`). --all-items also includes
items that have no content record yet. Only sources listed in config/feeds.yml are used.

API key: OPENROUTER_API_KEY, read from a .env file in the repo root (see .env.example).
A variable already set in the environment takes precedence over the file.

Usage:
    cp .env.example .env                         # once, then fill in OPENROUTER_API_KEY
    uv run python -m pnews.enrich --limit 5      # at most 5 API calls, to try it out
    uv run python -m pnews.enrich                # everything selected and not yet cached
    uv run python -m pnews.enrich --dry-run      # show what would be sent; no API calls
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pnews.collect import load_feeds
from pnews.content import load_content, load_items

ENTITY_TYPES = ("organization", "person", "product", "location")
USER_MARKER = "===USER==="
# Trailing company-form words dropped when building the entity key ("OpenAI Inc." == "OpenAI").
COMPANY_SUFFIXES = {"inc", "incorporated", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "gmbh", "ag", "sa"}


# ---------------------------------------------------------------- config / prompt / IO


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {"api_url", "model", "prompt_file", "prompt_version", "temperature", "seed",
                "max_tokens", "max_input_words", "min_interval_s"}
    missing = required - cfg.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    return cfg


def load_prompt(path: Path) -> tuple[str, str]:
    """(system message, user template). The leading <!-- --> comment is documentation, not prompt."""
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"\A\s*<!--.*?-->\s*", "", raw, flags=re.S)
    if raw.count(USER_MARKER) != 1:
        raise ValueError(f"{path}: expected exactly one {USER_MARKER} line")
    system, user = raw.split(USER_MARKER)
    return system.strip(), user.strip()


def load_aliases(path: Path) -> dict[str, str]:
    """alias -> canonical name, compared after basic normalization."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = {}
    for canonical, aliases in (data.get("aliases") or {}).items():
        for alias in [canonical, *(aliases or [])]:
            out[_basic_norm(alias)] = canonical
    return out


def load_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    cache[row["input_hash"]] = row
    return cache


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


# ---------------------------------------------------------------- model input


def build_input(item: dict, content_rec: dict | None, max_words: int) -> dict:
    """Pick the text to send and cut it to max_words. Whitespace is collapsed; the grounding
    check runs against exactly this text (plus the title)."""
    if content_rec and content_rec.get("text"):
        text, source = content_rec["text"], "article"
    elif item.get("summary"):
        text, source = item["summary"], "summary"
    else:
        text, source = "", "title_only"
    words = text.split()
    return {
        "title": " ".join(item["title"].split()),
        "text": " ".join(words[:max_words]),
        "text_source": source,
        "input_words": min(len(words), max_words),
        "truncated": len(words) > max_words,
    }


def render_user(template: str, source_name: str, title: str, text: str) -> str:
    # str.replace, not str.format: article text may contain braces.
    return template.replace("{source_name}", source_name).replace("{title}", title).replace("{text}", text)


def input_hash(cfg: dict, messages: list[dict]) -> str:
    key = {
        "model": cfg["model"],
        "prompt_version": cfg["prompt_version"],
        "temperature": cfg["temperature"],
        "seed": cfg["seed"],
        "max_tokens": cfg["max_tokens"],
        "json_mode": bool(cfg.get("json_mode")),
        "reasoning": cfg.get("reasoning"),
        "routing": cfg.get("routing"),
        "messages": messages,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- API


def get_api_key(env_file: Path) -> str | None:
    """OPENROUTER_API_KEY from the environment, else from env_file (.env). Never logged or stored."""
    load_dotenv(env_file, override=False)
    return os.environ.get("OPENROUTER_API_KEY") or None


class RateLimiter:
    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep) -> None:
        self.min_interval, self.clock, self.sleep = min_interval, clock, sleep
        self.last: float | None = None

    def wait(self) -> None:
        if self.last is not None:
            remaining = self.min_interval - (self.clock() - self.last)
            if remaining > 0:
                self.sleep(remaining)
        self.last = self.clock()


class ApiError(RuntimeError):
    pass


def call_openrouter(cfg: dict, messages: list[dict], api_key: str, limiter: RateLimiter) -> dict:
    """One chat completion. Retries rate limits (429) and server errors with backoff.
    Returns {"content", "model", "provider", "usage"}. Raises ApiError when it gives up."""
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"],
        "seed": cfg["seed"],
        "max_tokens": cfg["max_tokens"],
    }
    if cfg.get("json_mode"):
        payload["response_format"] = {"type": "json_object"}
    if cfg.get("reasoning"):
        payload["reasoning"] = cfg["reasoning"]
    if cfg.get("routing"):
        payload["provider"] = cfg["routing"]  # OpenRouter provider preferences
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "pnews course project",
    }
    retries = cfg.get("max_rate_limit_retries", 5)
    for attempt in range(retries + 1):
        limiter.wait()
        req = urllib.request.Request(cfg["api_url"], data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=cfg.get("request_timeout_s", 120)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code == 429 or exc.code >= 500:
                if attempt < retries:
                    _backoff(limiter, attempt, exc.headers.get("Retry-After"))
                    continue
            raise ApiError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                _backoff(limiter, attempt, None)
                continue
            raise ApiError(f"network error: {exc}") from exc

        # OpenRouter can answer 200 with an error object (e.g. upstream rate limit).
        if "error" in data:
            code = (data["error"] or {}).get("code")
            if code in (429, 502, 503) and attempt < retries:
                _backoff(limiter, attempt, None)
                continue
            raise ApiError(f"API error: {json.dumps(data['error'])[:300]}")
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError(f"unexpected response shape: {json.dumps(data)[:300]}") from exc
        return {
            "content": content,
            "finish_reason": choice.get("finish_reason"),  # "length" = cut off at max_tokens
            "model": data.get("model"),
            "provider": data.get("provider"),
            "usage": data.get("usage"),
        }
    raise ApiError("gave up after retries")


def _backoff(limiter: RateLimiter, attempt: int, retry_after: str | None) -> None:
    try:
        delay = float(retry_after) if retry_after else 0.0
    except ValueError:
        delay = 0.0
    delay = max(delay, 10 * 2**attempt)  # 10, 20, 40, ... seconds
    print(f"    rate limited or server error; waiting {delay:.0f}s")
    limiter.sleep(delay)


# ---------------------------------------------------------------- validation


def parse_json(raw: str) -> dict:
    """The JSON object in the answer. Tolerates ```json fences and text around the object."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the answer")
    obj = json.loads(s[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("top level is not a JSON object")
    return obj


def schema_errors(obj: dict) -> list[str]:
    errors = []
    ents = obj.get("entities")
    if not isinstance(ents, list):
        return ['"entities" must be a list']
    for i, e in enumerate(ents):
        if not isinstance(e, dict):
            errors.append(f"entities[{i}] is not an object")
            continue
        for key in ("name", "type", "mention"):
            if not isinstance(e.get(key), str) or not e[key].strip():
                errors.append(f"entities[{i}].{key} must be a non-empty string")
        if isinstance(e.get("type"), str) and e["type"] not in ENTITY_TYPES:
            errors.append(f"entities[{i}].type {e['type']!r} is not one of {list(ENTITY_TYPES)}")
    return errors


def check_answer(raw: str) -> tuple[list[dict] | None, list[str]]:
    """(entities, []) if the answer parses and matches the schema, else (None, errors)."""
    try:
        obj = parse_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, [f"invalid JSON: {exc}"]
    errors = schema_errors(obj)
    return (None, errors) if errors else (obj["entities"], [])


# Typographic dashes and quotes -> ASCII. OpenAI writes "GPT-5.5" with a non-breaking
# hyphen (U+2011) while models often answer with "-"; both must give the same key.
_PUNCT_MAP = str.maketrans({
    **{c: "-" for c in "‐‑‒–—―−﹘﹣－"},
    "‘": "'", "’": "'", "“": '"', "”": '"',
})


def _fold(s: str) -> str:
    """Case-, width-, dash- and whitespace-insensitive form for matching."""
    s = unicodedata.normalize("NFKC", s).casefold().translate(_PUNCT_MAP)
    return " ".join(s.split())


def _basic_norm(name: str) -> str:
    """Key form of a name: folded, commas dropped, periods dropped except inside numbers
    ("U.S." -> "us", "Node.js" -> "nodejs", but "GPT-5.5" keeps "5.5")."""
    s = _fold(name).replace(",", "")
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", "", s)
    return " ".join(s.split())


def entity_key(etype: str, name: str, aliases: dict[str, str]) -> tuple[str, str]:
    """(entity_id, canonical name). entity_id = "<type>:<normalized name>"."""
    canonical = aliases.get(_basic_norm(name), name.strip())
    norm = _basic_norm(canonical)
    if etype == "organization":
        words = norm.split()
        while len(words) > 1 and words[-1] in COMPANY_SUFFIXES:
            words.pop()
        norm = " ".join(words)
    return f"{etype}:{norm}", canonical


def mention_in_text(mention: str, folded_text: str) -> bool:
    """Whole-word, case-insensitive match, so "US" does not match inside "status"."""
    m = _fold(mention)
    return bool(m) and re.search(rf"(?<!\w){re.escape(m)}(?!\w)", folded_text) is not None


def ground_and_normalize(entities: list[dict], title: str, text: str, aliases: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Keep entities whose mention is in the input; give each an entity_id; merge duplicates."""
    haystack = _fold(f"{title} {text}")
    kept, dropped, seen = [], [], set()
    for e in entities:
        name, etype, mention = e["name"].strip(), e["type"], e["mention"].strip()
        if not mention_in_text(mention, haystack):
            dropped.append({"name": name, "type": etype, "mention": mention, "reason": "mention not in input"})
            continue
        eid, canonical = entity_key(etype, name, aliases)
        if eid in seen:
            continue  # same entity listed twice (or two aliases of it)
        seen.add(eid)
        kept.append({"entity_id": eid, "name": canonical, "type": etype, "mention": mention})
    return kept, dropped


# ---------------------------------------------------------------- per item


def request_with_retry(cfg: dict, messages: list[dict], call) -> list[dict]:
    """First call; if the answer fails parse/schema, one retry showing the errors. Returns attempt records."""
    first = call(messages)
    attempts = [{**first, "retry": False}]
    _, errors = check_answer(first["content"])
    if errors:
        retry_msgs = messages + [
            {"role": "assistant", "content": first["content"]},
            {"role": "user", "content": "Your answer was not valid: " + "; ".join(errors[:5])
             + ". Reply again with JSON only, in the required shape."},
        ]
        attempts.append({**call(retry_msgs), "retry": True})
    return attempts


def derive_output(item: dict, inp: dict, row: dict, aliases: dict[str, str]) -> dict:
    """Validated output for one item from its cache row (no API calls)."""
    out = {
        "item_id": item["item_id"],
        "source_id": item["source_id"],
        "status": "fallback",
        "entities": [],
        "dropped": [],
        "errors": [],
        "attempt_used": None,
        "text_source": inp["text_source"],
        "input_words": inp["input_words"],
        "truncated": inp["truncated"],
        "input_hash": row["input_hash"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
    }
    for n, attempt in enumerate(row["attempts"], 1):
        entities, errors = check_answer(attempt["content"])
        if attempt.get("finish_reason") == "length":
            errors = [*errors, "answer cut off at max_tokens (finish_reason=length)"]
        if entities is None:
            out["errors"].append({"attempt": n, "errors": errors})
            continue
        kept, dropped = ground_and_normalize(entities, inp["title"], inp["text"], aliases)
        out.update(status="ok", entities=kept, dropped=dropped, attempt_used=n)
        break
    return out


# ---------------------------------------------------------------- run


def run(args) -> int:
    cfg = load_config(args.config)
    system, user_tpl = load_prompt(Path(cfg["prompt_file"]))
    aliases = load_aliases(args.aliases)
    feeds = {f["id"]: f for f in load_feeds(args.feeds)}
    if args.source:
        unknown = sorted(set(args.source) - feeds.keys())
        if unknown:
            raise SystemExit(f"--source not in {args.feeds}: {', '.join(unknown)}")
    sources = set(args.source) if args.source else set(feeds)

    content = load_content(args.content)
    items = [i for i in load_items(args.items)
             if i["source_id"] in sources and (args.all_items or i["item_id"] in content)]

    # Build every input first; the hash decides what is already cached.
    jobs = []
    for item in items:
        inp = build_input(item, content.get(item["item_id"]), cfg["max_input_words"])
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": render_user(user_tpl, feeds[item["source_id"]]["name"], inp["title"], inp["text"])},
        ]
        jobs.append((item, inp, messages, input_hash(cfg, messages)))

    cache = load_cache(args.cache)
    todo = [j for j in jobs if j[3] not in cache]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(f"{len(jobs)} items selected, {len(jobs) - len([j for j in jobs if j[3] not in cache])} cached, {len(todo)} to send")

    if args.dry_run:
        for item, inp, messages, h in todo[:3]:
            print(f"\n--- {item['item_id']} ({item['source_id']}, {inp['text_source']}, {inp['input_words']} words)")
            print(messages[1]["content"][:800])
        return 0

    api_errors = 0
    if todo:
        api_key = get_api_key(args.env_file)
        if not api_key:
            raise SystemExit(f"OPENROUTER_API_KEY is not set: add it to {args.env_file} (see .env.example)")
        limiter = RateLimiter(cfg["min_interval_s"])
        call = lambda msgs: call_openrouter(cfg, msgs, api_key, limiter)  # noqa: E731
        for n, (item, inp, messages, h) in enumerate(todo, 1):
            try:
                attempts = request_with_retry(cfg, messages, call)
            except ApiError as exc:
                api_errors += 1
                print(f"[{n}/{len(todo)}] API error {item['item_id']}: {exc}")
                continue  # not cached; the next run tries again
            row = {
                "input_hash": h,
                "item_id": item["item_id"],
                "model": cfg["model"],
                "prompt_version": cfg["prompt_version"],
                "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "attempts": attempts,
            }
            append_jsonl(args.cache, row)
            cache[h] = row
            out = derive_output(item, inp, row, aliases)
            print(f"[{n}/{len(todo)}] {out['status']:8} {len(out['entities']):>3} entities"
                  f" ({len(out['dropped'])} dropped)  {item['source_id']:18} {item['title'][:60]}")

    outputs = [derive_output(item, inp, cache[h], aliases) for item, inp, _, h in jobs if h in cache]
    write_jsonl(args.out, outputs)
    print_summary(outputs, len(jobs), api_errors, args.out)
    return 0


def print_summary(outputs: list[dict], selected: int, api_errors: int, out_path: Path) -> None:
    status = Counter(o["status"] for o in outputs)
    types = Counter(e["type"] for o in outputs for e in o["entities"])
    dropped = sum(len(o["dropped"]) for o in outputs)
    retried = sum(1 for o in outputs if o["attempt_used"] == 2)
    cut_off = sum(1 for o in outputs for e in o["errors"] if any("finish_reason=length" in x for x in e["errors"]))
    distinct = len({e["entity_id"] for o in outputs for e in o["entities"]})
    print(f"\nwrote {len(outputs)}/{selected} items to {out_path}: {dict(status)}; retried {retried}; "
          f"cut off at max_tokens {cut_off}; API errors this run {api_errors}")
    print(f"entities kept: {sum(types.values())} ({distinct} distinct) {dict(types)}; dropped (not in input): {dropped}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=Path("config/enrich.yml"))
    ap.add_argument("--env-file", type=Path, default=Path(".env"), help="file with OPENROUTER_API_KEY")
    ap.add_argument("--feeds", type=Path, default=Path("config/feeds.yml"))
    ap.add_argument("--aliases", type=Path, default=Path("config/entity_aliases.yml"))
    ap.add_argument("--items", type=Path, default=Path("data/items.jsonl"))
    ap.add_argument("--content", type=Path, default=Path("data/content.jsonl"))
    ap.add_argument("--cache", type=Path, default=Path("data/enrichment/cache.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("data/enrichment/entities.jsonl"))
    ap.add_argument("--source", action="append", help="only this source_id (repeatable)")
    ap.add_argument("--all-items", action="store_true", help="also items without a content record (uses the feed summary)")
    ap.add_argument("--limit", type=int, help="send at most N items to the API this run")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent; no API calls, no files written")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
