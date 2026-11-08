"""Offline tests for pnews.collect: inline XML, no network."""

import json

from pnews import collect

FEED = {"id": "test", "name": "Test", "url": "https://example.com/feed"}
NOW = "2026-11-07T12:00:00+00:00"

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>T</title>
<item><title>First &amp; best</title><link>https://www.Example.com/a/?utm_source=rss&amp;id=2#top</link>
<guid>a-1</guid><pubDate>Fri, 06 Nov 2026 10:00:00 -0500</pubDate>
<description>&lt;p&gt;Short &lt;b&gt;summary&lt;/b&gt;&lt;/p&gt;</description>
<content:encoded><![CDATA[<p>one two three four</p><script>evil()</script>]]></content:encoded></item>
<item><title>No date</title><link>https://example.com/b</link></item>
<item><title>Bad link</title><link>javascript:alert(1)</link></item>
<item><title>Same as first</title><link>http://example.com/a?id=2</link></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Atom entry</title><link rel="alternate" href="https://example.org/post"/>
<id>tag:example.org,2026:1</id><updated>2026-11-05T08:00:00Z</updated>
<summary>Atom summary</summary><author><name>Ann</name></author><category term="ai"/></entry>
</feed>"""


def _items(body):
    parsed = collect.parse_feed_bytes(body)
    return [collect.normalize_entry(e, FEED, NOW) for e in parsed.entries]


def test_normalize_url():
    n = collect.normalize_url
    assert n("https://www.Example.com/a/?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
    assert n("http://example.com/a") == n("https://example.com/a/")
    assert n("https://example.com") == "https://example.com/"
    assert n("https://example.com:8080/x") == "https://example.com:8080/x"
    assert n("javascript:alert(1)") is None
    assert n("") is None


def test_html_to_text_strips_tags_scripts_entities():
    assert collect.html_to_text("<p>a &amp; <b>b</b></p><script>x()</script><p>c</p>") == "a & b c"
    assert collect.html_to_text(None) == ""


def test_rss_entry_normalized():
    (item, err), (no_date, _), (bad, reason), (dup, _) = _items(RSS)
    assert err is None
    assert item["title"] == "First & best"
    assert item["summary"] == "Short summary"
    assert item["url_normalized"] == "https://example.com/a?id=2"
    assert item["published_at"] == "2026-11-06T15:00:00+00:00"  # converted to UTC
    assert item["date_field"] == "published"
    assert "updated_at" not in item  # only published_at is stored
    assert item["feed_content_words"] == 4  # script text excluded
    assert item["guid"] == "a-1"
    assert no_date["published_at"] is None and no_date["date_field"] is None
    assert bad is None and reason == "no http(s) link"
    assert dup["item_id"] == item["item_id"]  # http vs https, trailing slash, tracking params


def test_atom_entry_uses_updated_and_alternate_link():
    [(item, err)] = _items(ATOM)
    assert err is None
    assert item["url"] == "https://example.org/post"
    assert item["date_field"] == "updated"
    assert item["published_at"] == "2026-11-05T08:00:00+00:00"
    assert item["author"] == "Ann"
    assert item["feed_tags"] == ["ai"]


def test_long_summary_truncated():
    body = b"<rss version='2.0'><channel><item><title>x</title><link>https://e.com/x</link><description>" + b"w " * 200 + b"</description></item></channel></rss>"
    [(item, _)] = _items(body)
    assert item["summary_truncated"] is True
    assert len(item["summary"].split()) == 121  # 120 words + ellipsis


def test_collect_feed_dedupes_and_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "download", lambda url: (RSS, {}, 200))
    out = tmp_path / "items.jsonl"
    seen = collect.load_existing_ids(out)
    items, rep = collect.collect_feed(FEED, seen, tmp_path / "raw", NOW)
    collect.append_items(out, items)
    assert (rep.entries, rep.new, rep.duplicate, rep.skipped) == (4, 2, 1, {"no http(s) link": 1})
    assert rep.raw_path and (tmp_path / "raw" / "test").is_dir()

    # Second run: everything already stored.
    seen = collect.load_existing_ids(out)
    items2, rep2 = collect.collect_feed(FEED, seen, None, NOW)
    assert items2 == [] and rep2.duplicate == 3
    assert len(out.read_text().splitlines()) == 2
    assert all(json.loads(line)["source_id"] == "test" for line in out.read_text().splitlines())
    assert all(next(iter(json.loads(line))) == "item_id" for line in out.read_text().splitlines())  # id first


def test_parse_since():
    assert collect.parse_since("2026").isoformat() == "2026-01-01T00:00:00+00:00"
    assert collect.parse_since("2026-03").isoformat() == "2026-03-01T00:00:00+00:00"
    assert collect.parse_since("2026-03-15").isoformat() == "2026-03-15T00:00:00+00:00"


def test_since_filter_skips_old_and_undated(monkeypatch):
    monkeypatch.setattr(collect, "download", lambda url: (RSS, {}, 200))
    # Fixture: one dated item (2026-11-06); "No date" and "Same as first" have no date; one bad link.
    items, rep = collect.collect_feed(FEED, set(), None, NOW, collect.parse_since("2026"))
    assert [i["title"] for i in items] == ["First & best"]
    assert rep.skipped == {"no date": 2, "no http(s) link": 1}

    items, rep = collect.collect_feed(FEED, set(), None, NOW, collect.parse_since("2026-11-07"))
    assert items == []
    assert rep.skipped == {"before --since": 1, "no date": 2, "no http(s) link": 1}


def test_decode_body_handles_compression():
    import gzip
    import zlib

    assert collect.decode_body(gzip.compress(RSS), {"content-encoding": "gzip"}) == RSS
    assert collect.decode_body(gzip.compress(RSS), {}) == RSS  # header missing: gzip magic bytes
    assert collect.decode_body(zlib.compress(RSS), {"content-encoding": "deflate"}) == RSS
    raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    assert collect.decode_body(raw.compress(RSS) + raw.flush(), {"content-encoding": "deflate"}) == RSS
    assert collect.decode_body(RSS, {}) == RSS  # plain body untouched
    # The parsed result matches the uncompressed feed.
    assert len(collect.parse_feed_bytes(collect.decode_body(gzip.compress(RSS), {})).entries) == 4
