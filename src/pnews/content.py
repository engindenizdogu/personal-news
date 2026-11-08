"""Fetch each item's article page and extract the main text with trafilatura.

Reads data/items.jsonl, downloads every item's `url`, extracts the article text,
and appends one record per item to data/content.jsonl (git-ignored: full article
text stays out of the repo). The raw HTML is kept gzipped in data/raw/html/ so the
text can be re-extracted later without fetching again.

Records are keyed by `item_id`, the same id as in items.jsonl. Every attempted item
gets a record; when no text could be extracted, `text` and `words` are null and
`status` says why. If an item has more than one record (after --retry-failed), the
last one wins; use `load_content()`.

Only items whose source is still listed in config/feeds.yml are fetched, so removing
a feed from the config also stops fetching its old items.

Rules:
- robots.txt is respected for our User-Agent; disallowed pages are not fetched.
- At most one request per host every PER_HOST_DELAY_S seconds.
- Only HTML pages are extracted; PDFs, images, etc. get status `unsupported_type`.
- Page content is untrusted data. It is stored as text and never interpreted.

Statuses: ok, too_short, no_text, unsupported_type, http_error, fetch_error,
too_large, robots_disallowed.

Usage:
    uv run python -m pnews.content                      # every item without a record yet
    uv run python -m pnews.content --limit 20           # try a small sample first
    uv run python -m pnews.content --per-source 5       # at most 5 items from each source
    uv run python -m pnews.content --source deepmind --source stripe
    uv run python -m pnews.content --retry-failed       # also retry items whose last record failed
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.robotparser
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import trafilatura

from pnews.collect import USER_AGENT, http_get, load_feeds

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
PAGE_TIMEOUT_S = 20
PER_HOST_DELAY_S = 1.0
MIN_WORDS = 50  # below this, extraction probably caught a teaser, paywall or error page

HTML_TYPES = ("text/html", "application/xhtml+xml")
EXTRACTOR = f"trafilatura {trafilatura.__version__}"
# Changing these changes the extracted text; bump EXTRACT_SETTINGS_VERSION when you do.
EXTRACT_SETTINGS_VERSION = "v1"
EXTRACT_KWARGS = dict(
    output_format="txt",
    include_comments=False,
    include_tables=False,
    include_images=False,
    include_links=False,
    favor_precision=True,
)


# ---------------------------------------------------------------- IO


def load_items(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_content(path: Path) -> dict[str, dict]:
    """item_id -> latest content record."""
    records: dict[str, dict] = {}
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    records[rec["item_id"]] = rec
    return records


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_html(html_dir: Path, item_id: str, body: bytes) -> None:
    html_dir.mkdir(parents=True, exist_ok=True)
    (html_dir / f"{item_id}.html.gz").write_bytes(gzip.compress(body))


# ---------------------------------------------------------------- politeness


class HostThrottle:
    """Wait so that requests to the same host are at least `delay` seconds apart."""

    def __init__(self, delay: float, clock=time.monotonic, sleep=time.sleep) -> None:
        self.delay, self.clock, self.sleep = delay, clock, sleep
        self.last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        if host in self.last:
            remaining = self.delay - (self.clock() - self.last[host])
            if remaining > 0:
                self.sleep(remaining)
        self.last[host] = self.clock()


class RobotsCache:
    """One robots.txt fetch per host. Follows the urllib.robotparser conventions:
    401/403 -> disallow everything, other 4xx -> allow everything.
    Network errors and 5xx -> allow (we could not read a rule, so there is none to respect)."""

    def __init__(self, throttle: HostThrottle) -> None:
        self.throttle = throttle
        self.parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.parsers:
            self.parsers[base] = self._load(base + "/robots.txt")
        return self.parsers[base].can_fetch(USER_AGENT, url)

    def _load(self, robots_url: str) -> urllib.robotparser.RobotFileParser:
        rp = urllib.robotparser.RobotFileParser(robots_url)
        self.throttle.wait(robots_url)
        try:
            body, _, _, _ = http_get(robots_url, "text/plain, */*;q=0.5", MAX_ROBOTS_BYTES, PAGE_TIMEOUT_S)
            rp.parse(body.decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                rp.disallow_all = True
            else:
                rp.allow_all = True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            rp.allow_all = True
        return rp


# ---------------------------------------------------------------- extraction


def extract_text(html: bytes, url: str | None) -> str:
    """Main article text, or "" if trafilatura finds none."""
    text = trafilatura.extract(html, url=url, **EXTRACT_KWARGS)
    return (text or "").strip()


def fetch_content(item: dict, robots: RobotsCache, throttle: HostThrottle, html_dir: Path | None) -> dict:
    """Fetch one item's page and extract its text. Always returns a record; never raises for page problems."""
    url = item["url"]
    rec = {
        "item_id": item["item_id"],
        "source_id": item["source_id"],
        "url": url,
        "final_url": None,
        "status": None,
        "http_status": None,
        "content_type": None,
        "words": None,  # null when no text was extracted
        "text": None,
        "error": None,
        "extractor": EXTRACTOR,
        "extract_settings": EXTRACT_SETTINGS_VERSION,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }

    if urlsplit(url).scheme not in ("http", "https"):
        return {**rec, "status": "fetch_error", "error": "not an http(s) url"}
    if not robots.allowed(url):
        return {**rec, "status": "robots_disallowed"}

    throttle.wait(url)
    try:
        body, headers, status, final_url = http_get(
            url, "text/html, application/xhtml+xml;q=0.9, */*;q=0.5", MAX_PAGE_BYTES, PAGE_TIMEOUT_S
        )
    except urllib.error.HTTPError as exc:
        return {**rec, "status": "http_error", "http_status": exc.code, "error": str(exc)[:200]}
    except ValueError as exc:
        return {**rec, "status": "too_large", "error": str(exc)[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {**rec, "status": "fetch_error", "error": str(exc)[:200]}

    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    rec.update(final_url=final_url, http_status=status, content_type=content_type or None)
    if content_type and content_type not in HTML_TYPES:
        return {**rec, "status": "unsupported_type"}

    if html_dir is not None:
        save_html(html_dir, item["item_id"], body)

    text = extract_text(body, final_url)
    if not text:
        return {**rec, "status": "no_text"}  # text and words stay null
    words = len(text.split())
    status_name = "too_short" if words < MIN_WORDS else "ok"  # too_short keeps its text, but is flagged
    return {**rec, "status": status_name, "words": words, "text": text}


# ---------------------------------------------------------------- run


def select_items(
    items: list[dict],
    done: dict[str, dict],
    sources: list[str] | None,
    retry_failed: bool,
    per_source: int | None = None,
) -> list[dict]:
    """Items still to fetch, in items.jsonl order.

    sources: only these source_ids. per_source: at most N items from each source
    (the first N still to fetch, so repeated runs move on to the next N)."""
    todo, taken = [], Counter()
    for item in items:
        sid = item["source_id"]
        if sources is not None and sid not in sources:
            continue
        prev = done.get(item["item_id"])
        if prev is not None and not (retry_failed and prev["status"] != "ok"):
            continue
        if per_source is not None and taken[sid] >= per_source:
            continue
        taken[sid] += 1
        todo.append(item)
    return todo


def run(items_path: Path, feeds_path: Path, out_path: Path, html_dir: Path | None, sources: list[str] | None,
        limit: int | None, retry_failed: bool, per_source: int | None = None) -> dict[str, Counter]:
    items = load_items(items_path)
    configured = {f["id"] for f in load_feeds(feeds_path)}
    unknown = sorted(set(sources or []) - configured)
    if unknown:
        raise SystemExit(f"--source not in {feeds_path}: {', '.join(unknown)}")
    dropped = Counter(i["source_id"] for i in items if i["source_id"] not in configured)
    if dropped:
        print("skipping sources no longer in the feed config: " + ", ".join(f"{k} ({v})" for k, v in sorted(dropped.items())))
    allowed = sorted(set(sources) if sources else configured)
    todo = select_items(items, load_content(out_path), allowed, retry_failed, per_source)
    if limit is not None:
        todo = todo[:limit]
    print(f"{len(todo)} items to fetch")

    throttle = HostThrottle(PER_HOST_DELAY_S)
    robots = RobotsCache(throttle)
    stats: dict[str, Counter] = defaultdict(Counter)
    for n, item in enumerate(todo, 1):
        rec = fetch_content(item, robots, throttle, html_dir)
        append_record(out_path, rec)  # one at a time, so an interrupted run keeps its progress
        stats[item["source_id"]][rec["status"]] += 1
        words = "-" if rec["words"] is None else rec["words"]
        print(f"[{n}/{len(todo)}] {rec['status']:17} {words:>6}w  {item['source_id']:18} {item['url'][:80]}")
    return stats


def print_stats(stats: dict[str, Counter]) -> None:
    statuses = sorted({s for c in stats.values() for s in c})
    if not statuses:
        return
    print("\n" + f"{'source':20}" + "".join(f"{s:>18}" for s in statuses))
    for source, counts in sorted(stats.items()):
        print(f"{source:20}" + "".join(f"{counts.get(s, 0):>18}" for s in statuses))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--items", type=Path, default=Path("data/items.jsonl"))
    ap.add_argument("--feeds", type=Path, default=Path("config/feeds.yml"))
    ap.add_argument("--out", type=Path, default=Path("data/content.jsonl"))
    ap.add_argument("--html-dir", type=Path, default=Path("data/raw/html"))
    ap.add_argument("--no-html", action="store_true", help="don't keep the raw HTML")
    ap.add_argument("--source", action="append", help="only this source_id (repeatable)")
    ap.add_argument("--limit", type=int, help="fetch at most N items in total")
    ap.add_argument("--per-source", type=int, metavar="N", help="fetch at most N items from each source")
    ap.add_argument("--retry-failed", action="store_true", help="also re-fetch items whose last record is not ok")
    args = ap.parse_args(argv)

    stats = run(args.items, args.feeds, args.out, None if args.no_html else args.html_dir,
                args.source, args.limit, args.retry_failed, args.per_source)
    print_stats(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
