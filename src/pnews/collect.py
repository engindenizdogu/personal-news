"""Collect items from the RSS/Atom feeds in config/feeds.yml.

For each feed: download the XML, save a raw snapshot, parse it with feedparser,
normalize every entry to one item record, drop items already seen (by normalized
URL), and append the new ones to data/items.jsonl.

With --since, items published before that date, or with no date at all, are skipped
(and counted in the report). Without it, every entry the feed exposes is kept.
Skipped items are not stored; the raw XML snapshot still has them.

Feed content is untrusted data. We only store it as text; nothing here interprets it.

Usage:
    uv run python -m pnews.collect
    uv run python -m pnews.collect --since 2026
    uv run python -m pnews.collect --feeds config/feeds.yml --out data/items.jsonl --raw-dir data/raw/feeds
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import yaml

USER_AGENT = "pnews-course-project/0.1 (personal research; RSS reader)"
TIMEOUT_S = 30
MAX_FEED_BYTES = 20 * 1024 * 1024  # refuse absurdly large responses

# Query parameters that only track clicks; dropping them lets the same story dedupe.
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid", "ocid"}
TRACKING_PREFIXES = ("utm_",)


# ---------------------------------------------------------------- config / IO


def load_feeds(path: Path) -> list[dict]:
    """Read config/feeds.yml and check each feed has a unique id, a name and an http(s) url."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = data.get("feeds") or []
    seen: set[str] = set()
    for f in feeds:
        missing = {"id", "name", "url"} - f.keys()
        if missing:
            raise ValueError(f"feed {f!r} is missing {sorted(missing)}")
        if f["id"] in seen:
            raise ValueError(f"duplicate feed id {f['id']!r}")
        if urlsplit(f["url"]).scheme not in ("http", "https"):
            raise ValueError(f"feed {f['id']!r}: url must be http(s)")
        seen.add(f["id"])
    return feeds


def load_existing_ids(path: Path) -> set[str]:
    """Item ids already in items.jsonl, so re-running the collector never duplicates items."""
    if not path.exists():
        return set()
    ids = set()
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ids.add(json.loads(line)["item_id"])
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no}: unreadable item ({exc})") from exc
    return ids


def append_items(path: Path, items: list[dict]) -> None:
    """Append rows as JSON lines. Keys keep their insertion order, so `item_id` comes first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def decode_body(body: bytes, headers: dict[str, str], max_bytes: int = MAX_FEED_BYTES) -> bytes:
    """Undo gzip/deflate compression. urllib does not do this itself, and some servers
    (e.g. deepmind.google) compress even when the request did not ask for it.
    Also checks the gzip magic bytes in case the Content-Encoding header is missing."""
    encoding = headers.get("content-encoding", "").lower().strip()
    if encoding in ("gzip", "x-gzip") or body[:2] == b"\x1f\x8b":
        wbits = 16 + zlib.MAX_WBITS  # gzip wrapper
    elif encoding == "deflate":
        wbits = zlib.MAX_WBITS if body[:1] == b"\x78" else -zlib.MAX_WBITS  # zlib-wrapped or raw
    else:
        return body
    out = zlib.decompressobj(wbits).decompress(body, max_bytes + 1)  # cap guards against zip bombs
    if len(out) > max_bytes:
        raise ValueError(f"decompressed response larger than {max_bytes} bytes")
    return out


def http_get(url: str, accept: str, max_bytes: int, timeout: float = TIMEOUT_S) -> tuple[bytes, dict[str, str], int, str]:
    """GET with our User-Agent, decompression and size cap.

    Returns (decompressed body, lowercase headers, HTTP status, final URL after redirects).
    Raises urllib.error.HTTPError for 4xx/5xx, other URLError/OSError for network problems,
    ValueError when the response is too large.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip, deflate"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError(f"response larger than {max_bytes} bytes")
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = decode_body(body, headers, max_bytes)
        headers.pop("content-encoding", None)  # body is now plain bytes
        return body, headers, resp.status, resp.geturl()


def download(url: str) -> tuple[bytes, dict[str, str], int]:
    """GET a feed. Returns (decompressed body, lowercase headers, HTTP status). Raises on network/HTTP errors."""
    body, headers, status, _ = http_get(
        url, "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5", MAX_FEED_BYTES
    )
    return body, headers, status


def save_raw(raw_dir: Path, feed_id: str, fetched_at: str, body: bytes) -> Path:
    """Keep the XML exactly as received (git-ignored). Lets us re-parse without re-fetching."""
    stamp = fetched_at.replace(":", "").replace("-", "")
    out = raw_dir / feed_id / f"{stamp}.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return out


# ---------------------------------------------------------------- normalization


def normalize_url(url: str) -> str | None:
    """Canonical form used for the item id and dedupe. Returns None for non-http(s) links.

    - lowercase scheme and host, drop "www.", drop default ports
    - drop the fragment and tracking query params; sort the rest
    - drop a trailing slash (except for the root path)
    - treat http and https as the same page (key always uses https)
    """
    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def parse_since(value: str) -> datetime:
    """'2026', '2026-03' or '2026-03-15' (or a full ISO timestamp) -> start of that period, UTC."""
    v = value.strip()
    if re.fullmatch(r"\d{4}", v):
        v += "-01-01"
    elif re.fullmatch(r"\d{4}-\d{2}", v):
        v += "-01"
    dt = datetime.fromisoformat(v)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def date_filter_reason(item: dict, since: datetime | None) -> str | None:
    """Why the item fails the --since filter, or None if it passes (or there is no filter)."""
    if since is None:
        return None
    if not item["published_at"]:
        return "no date"
    if datetime.fromisoformat(item["published_at"]) < since:
        return "before --since"
    return None


def make_item_id(norm_url: str) -> str:
    return hashlib.sha256(norm_url.encode("utf-8")).hexdigest()[:16]


class _TextExtractor(HTMLParser):
    """Collect visible text from an HTML fragment (stdlib only; feed snippets are small)."""

    _BLOCK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre"}
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(fragment: str | None) -> str:
    """Strip tags, decode entities, collapse whitespace."""
    if not fragment:
        return ""
    parser = _TextExtractor()
    parser.feed(fragment)
    parser.close()
    text = unescape("".join(parser.parts))
    return re.sub(r"\s+", " ", text).strip()


def _iso_utc(struct: time.struct_time | None) -> str | None:
    # feedparser's *_parsed values are already converted to UTC.
    if not struct:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc).isoformat()


def _pick_link(entry) -> str | None:
    """The entry's article URL: `link`, else an alternate link, else a guid that is a URL."""
    if entry.get("link"):
        return entry["link"]
    for link in entry.get("links", []):
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link["href"]
    guid = entry.get("id", "")
    if guid.startswith(("http://", "https://")):
        return guid
    return None


def _content_html(entry) -> str:
    """Longest `content` block (Atom content / RSS content:encoded), or empty."""
    blocks = [c.get("value", "") for c in entry.get("content", []) or []]
    return max(blocks, key=len, default="")


def normalize_entry(entry, feed: dict, fetched_at: str) -> tuple[dict | None, str | None]:
    """Turn one feedparser entry into an item record.

    Returns (item, None) on success or (None, reason) when the entry is skipped.
    Full article text is NOT stored here (items.jsonl is committed; bodies stay out).
    We only record how many words of content the feed carried, for the content step.
    """
    link = _pick_link(entry)
    norm = normalize_url(link) if link else None
    if not norm:
        return None, "no http(s) link"

    title = html_to_text(entry.get("title"))
    if not title:
        return None, "no title"

    # dict.get, not entry.get: FeedParserDict maps a missing `updated_parsed` to
    # `published_parsed` (feedparser issue 310), which would fake an update date.
    # Only one date is kept (published_at). The update date is used only when the feed
    # has no publish date: e.g. Nature (RSS 1.0) has only <dc:date>, which feedparser
    # files as `updated`. date_field records which one was used.
    published = _iso_utc(dict.get(entry, "published_parsed"))
    updated = _iso_utc(dict.get(entry, "updated_parsed"))
    date_field = "published" if published else ("updated" if updated else None)

    content_html = _content_html(entry)
    summary = html_to_text(entry.get("summary"))
    content_text = html_to_text(content_html)
    # Some feeds put the full post in <description>; cap what we commit as "summary".
    summary_words = summary.split()
    summary_truncated = len(summary_words) > 120
    if summary_truncated:
        summary = " ".join(summary_words[:120]) + " …"

    tags = sorted({t.get("term", "").strip() for t in entry.get("tags", []) or [] if t.get("term")})

    item = {
        "item_id": make_item_id(norm),
        "source_id": feed["id"],
        "url": link.strip(),
        "url_normalized": norm,
        "guid": entry.get("id") or None,
        "title": title,
        "summary": summary,
        "summary_truncated": summary_truncated,
        "author": html_to_text(entry.get("author")) or None,
        "feed_tags": tags,
        "published_at": published or updated,
        "date_field": date_field,
        "feed_content_words": len(content_text.split()),
        "first_seen_at": fetched_at,
    }
    return item, None


# ---------------------------------------------------------------- collection


@dataclass
class FeedReport:
    feed_id: str
    status: int | None = None
    format: str | None = None
    entries: int = 0
    new: int = 0
    duplicate: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    parse_warning: str | None = None
    error: str | None = None
    raw_path: str | None = None


def parse_feed_bytes(body: bytes, headers: dict[str, str] | None = None):
    """Parse feed bytes; headers let feedparser detect the charset from Content-Type."""
    return feedparser.parse(body, response_headers=headers or {})


def collect_feed(
    feed: dict, seen_ids: set[str], raw_dir: Path | None, fetched_at: str, since: datetime | None = None
) -> tuple[list[dict], FeedReport]:
    """Fetch, snapshot and normalize one feed. Adds new item ids to `seen_ids`."""
    rep = FeedReport(feed_id=feed["id"])
    try:
        body, headers, rep.status = download(feed["url"])
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        rep.error = f"download failed: {exc}"
        return [], rep

    if raw_dir is not None:
        rep.raw_path = str(save_raw(raw_dir, feed["id"], fetched_at, body))

    parsed = parse_feed_bytes(body, headers)
    rep.format = parsed.get("version") or None
    rep.entries = len(parsed.entries)
    if parsed.get("bozo"):
        # Malformed XML: feedparser often still recovers entries, so keep going but report it.
        rep.parse_warning = repr(parsed.get("bozo_exception"))[:200]
    if not parsed.entries:
        rep.error = "no entries parsed"
        return [], rep

    new_items = []
    for entry in parsed.entries:
        item, reason = normalize_entry(entry, feed, fetched_at)
        if item is not None:
            reason = date_filter_reason(item, since)
            if reason:
                item = None
        if item is None:
            rep.skipped[reason] = rep.skipped.get(reason, 0) + 1
            continue
        if item["item_id"] in seen_ids:
            rep.duplicate += 1  # already stored, or seen earlier in this run (first source wins)
            continue
        seen_ids.add(item["item_id"])
        new_items.append(item)
    rep.new = len(new_items)
    return new_items, rep


def run(feeds_path: Path, out_path: Path, raw_dir: Path | None, since: datetime | None = None) -> list[FeedReport]:
    feeds = load_feeds(feeds_path)
    seen_ids = load_existing_ids(out_path)
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    reports = []
    for feed in feeds:
        items, rep = collect_feed(feed, seen_ids, raw_dir, fetched_at, since)
        append_items(out_path, items)  # per feed, so a crash later keeps earlier feeds' items
        reports.append(rep)
    return reports


def print_reports(reports: list[FeedReport]) -> None:
    print(f"{'feed':20} {'status':>6} {'format':>8} {'entries':>7} {'new':>5} {'dup':>5}  notes")
    for r in reports:
        notes = []
        if r.error:
            notes.append(f"ERROR {r.error}")
        if r.parse_warning:
            notes.append(f"parse warning {r.parse_warning}")
        if r.skipped:
            notes.append("skipped " + ", ".join(f"{k}: {v}" for k, v in r.skipped.items()))
        print(f"{r.feed_id:20} {r.status or '-':>6} {r.format or '-':>8} {r.entries:>7} {r.new:>5} {r.duplicate:>5}  {'; '.join(notes)}")
    print(f"total new items: {sum(r.new for r in reports)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--feeds", type=Path, default=Path("config/feeds.yml"))
    ap.add_argument("--out", type=Path, default=Path("data/items.jsonl"))
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw/feeds"))
    ap.add_argument("--no-raw", action="store_true", help="don't save raw XML snapshots")
    ap.add_argument(
        "--since",
        type=parse_since,
        metavar="DATE",
        help="keep only items published on/after DATE (YYYY, YYYY-MM or YYYY-MM-DD, UTC); items with no date are skipped",
    )
    args = ap.parse_args(argv)

    if args.since:
        print(f"keeping items published on/after {args.since.isoformat()}")
    reports = run(args.feeds, args.out, None if args.no_raw else args.raw_dir, args.since)
    print_reports(reports)
    return 1 if all(r.error for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
