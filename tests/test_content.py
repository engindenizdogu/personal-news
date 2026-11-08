"""Offline tests for pnews.content: HTTP is faked, no network."""

import urllib.error

import pytest

from pnews import content

ITEM = {"item_id": "abc123", "source_id": "test", "url": "https://example.com/post"}

SENTENCES = [
    "The team released a new version of the storage engine this week.",
    "It cuts write latency by about forty percent on large clusters.",
    "Engineers spent most of the year rewriting the compaction scheduler.",
    "The old design paused writes whenever background merges fell behind.",
    "The new scheduler spreads merges across idle periods instead.",
    "Early users report fewer timeouts during traffic spikes.",
]
ARTICLE_HTML = (
    "<html><head><title>Storage engine update</title></head><body>"
    "<nav><a href='/'>Home</a> <a href='/about'>About us</a> <a href='/jobs'>Careers</a></nav>"
    "<article><h1>Storage engine update</h1>"
    + "".join(f"<p>{' '.join(SENTENCES)}</p>" for _ in range(4))
    + "</article><footer>Copyright Example Corp. Subscribe to our newsletter.</footer></body></html>"
).encode()


class FakeWeb:
    """Stands in for collect.http_get: maps URL -> response or exception, records calls."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, accept, max_bytes, timeout=None):
        self.calls.append(url)
        resp = self.pages.get(url)
        if resp is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(resp, Exception):
            raise resp
        body, ctype = resp
        return body, {"content-type": ctype}, 200, url


@pytest.fixture
def fetch(monkeypatch, tmp_path):
    def _fetch(pages, item=ITEM):
        web = FakeWeb(pages)
        monkeypatch.setattr(content, "http_get", web)
        throttle = content.HostThrottle(0)
        rec = content.fetch_content(item, content.RobotsCache(throttle), throttle, tmp_path / "html")
        return rec, web

    return _fetch


def test_extracts_article_text(fetch, tmp_path):
    rec, _ = fetch({"https://example.com/post": (ARTICLE_HTML, "text/html; charset=utf-8")})
    assert rec["status"] == "ok"
    assert rec["words"] >= content.MIN_WORDS
    assert "compaction scheduler" in rec["text"]
    assert "Careers" not in rec["text"]  # navigation dropped
    assert rec["content_type"] == "text/html"
    assert (tmp_path / "html" / "abc123.html.gz").exists()


def test_robots_disallow_skips_fetch(fetch):
    item = {**ITEM, "url": "https://example.com/private/post"}
    pages = {
        "https://example.com/robots.txt": (b"User-agent: *\nDisallow: /private\n", "text/plain"),
        item["url"]: (ARTICLE_HTML, "text/html"),
    }
    rec, web = fetch(pages, item)
    assert rec["status"] == "robots_disallowed"
    assert item["url"] not in web.calls


def test_robots_403_disallows_everything(fetch):
    pages = {
        "https://example.com/robots.txt": urllib.error.HTTPError("x", 403, "Forbidden", {}, None),
        "https://example.com/post": (ARTICLE_HTML, "text/html"),
    }
    rec, _ = fetch(pages)
    assert rec["status"] == "robots_disallowed"


def test_non_html_not_extracted(fetch):
    rec, _ = fetch({"https://example.com/post": (b"%PDF-1.7 ...", "application/pdf")})
    assert rec["status"] == "unsupported_type"
    assert rec["text"] is None and rec["words"] is None  # row kept, text null


def test_http_error_recorded(fetch):
    rec, _ = fetch({"https://example.com/post": urllib.error.HTTPError("x", 403, "Forbidden", {}, None)})
    assert rec["status"] == "http_error" and rec["http_status"] == 403
    assert rec["text"] is None and rec["words"] is None


def test_short_page_flagged(fetch):
    html = b"<html><body><article><p>Subscribe to read this story in full today.</p></article></body></html>"
    rec, _ = fetch({"https://example.com/post": (html, "text/html")})
    assert rec["status"] in ("too_short", "no_text")
    if rec["status"] == "no_text":
        assert rec["text"] is None and rec["words"] is None
    else:
        assert rec["words"] < content.MIN_WORDS


def test_select_items_resume_and_retry():
    items = [{"item_id": i, "source_id": s} for i, s in [("a", "x"), ("b", "x"), ("c", "y")]]
    done = {"a": {"status": "ok"}, "b": {"status": "http_error"}}
    assert [i["item_id"] for i in content.select_items(items, done, None, False)] == ["c"]
    assert [i["item_id"] for i in content.select_items(items, done, None, True)] == ["b", "c"]
    assert [i["item_id"] for i in content.select_items(items, done, ["x"], True)] == ["b"]


def test_select_items_per_source():
    items = [{"item_id": f"{s}{n}", "source_id": s} for s in "xy" for n in range(4)]
    done = {"x0": {"status": "ok"}}
    picked = [i["item_id"] for i in content.select_items(items, done, None, False, per_source=2)]
    assert picked == ["x1", "x2", "y0", "y1"]  # already-fetched items don't count toward N


def test_run_skips_sources_not_in_config(tmp_path, monkeypatch):
    items = tmp_path / "items.jsonl"
    items.write_text('{"item_id": "a", "source_id": "kept", "url": "https://k.com/a"}\n'
                     '{"item_id": "b", "source_id": "removed", "url": "https://r.com/b"}\n')
    feeds = tmp_path / "feeds.yml"
    feeds.write_text('feeds:\n  - {id: kept, name: Kept, url: "https://k.com/feed"}\n')
    seen = []
    monkeypatch.setattr(content, "fetch_content", lambda item, *a: seen.append(item["item_id"]) or
                        {"item_id": item["item_id"], "status": "no_text", "words": None, "text": None})
    content.run(items, feeds, tmp_path / "content.jsonl", None, None, None, False)
    assert seen == ["a"]


def test_load_content_last_record_wins(tmp_path):
    out = tmp_path / "content.jsonl"
    content.append_record(out, {"item_id": "a", "status": "http_error"})
    content.append_record(out, {"item_id": "a", "status": "ok"})
    assert content.load_content(out)["a"]["status"] == "ok"


def test_host_throttle_waits_per_host():
    now, slept = [0.0], []
    throttle = content.HostThrottle(1.0, clock=lambda: now[0], sleep=slept.append)
    throttle.wait("https://a.com/1")
    throttle.wait("https://b.com/1")  # different host: no wait
    now[0] = 0.25
    throttle.wait("https://a.com/2")
    assert slept == [0.75]
