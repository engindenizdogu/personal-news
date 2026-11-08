# personal-news (EM 626 course project)

A personal news digest that learns what one reader finds relevant from their ratings, using graph models.
Scope, pipeline and timeline: [`PROJECT_PLAN.md`](PROJECT_PLAN.md).

## Setup
Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in `.python-version`.

```sh
uv sync                              # create .venv and install locked dependencies
export ANTHROPIC_API_KEY=...         # needed for enrichment and the digest note only
uv run pytest                        # run tests
```

## Running the pipeline
Run from the repo root. Stages are listed in pipeline order; more are added as they're built (`run_all.py` at the end).

### 1. Collect
```sh
uv run python -m pnews.collect             # fetch every feed in config/feeds.yml
uv run python -m pnews.collect --no-raw    # same, without saving raw XML snapshots
uv run python -m pnews.collect --since 2026  # keep only items published on/after 2026-01-01 (UTC)
```
- Input: `config/feeds.yml`
- Output: new items appended to `data/items.jsonl` (committed). Raw XML goes to `data/raw/feeds/<feed_id>/<timestamp>.xml` (git-ignored)
- Safe to re-run: items already stored are skipped. Prints a per-feed table (status, entries, new, duplicates, skipped)
- `--since DATE` (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`, UTC): skip items published before DATE and items with no date. Skipped items are not stored, but stay in the raw XML snapshot
- Options: `--feeds`, `--out`, `--raw-dir` override the default paths
- Each row starts with `item_id`, a 16-character hash of the normalized URL. It is the key that every later stage (content, enrichment, ratings, graph) uses to refer to an item

### 2. Content (article text)
```sh
uv run python -m pnews.content --limit 20                 # try a small sample first
uv run python -m pnews.content --per-source 5             # at most 5 items from each source
uv run python -m pnews.content                            # every item without a content record yet
uv run python -m pnews.content --source deepmind          # one source (repeatable)
uv run python -m pnews.content --retry-failed             # also retry items whose last attempt failed
```
- Input: `data/items.jsonl`, limited to sources still listed in `config/feeds.yml` (items from removed feeds are skipped)
- Output: a separate file; `items.jsonl` is never modified. One record per attempted item appended to `data/content.jsonl` (git-ignored), keyed by `item_id`. Failed items still get a record, with `text` and `words` set to `null` and `status` saying why. Fields: `status`, `words`, `text`, HTTP details, extractor version. Raw HTML goes to `data/raw/html/<item_id>.html.gz` (git-ignored; `--no-html` to skip)
- Text extraction: [trafilatura](https://trafilatura.readthedocs.io/), main text only (no comments, tables, links)
- Polite fetching: respects `robots.txt`, at most one request per host per second, 20 s timeout, 5 MB page limit. A full run over ~800 items takes 15+ minutes
- Statuses: `ok`, `too_short` (< 50 words), `no_text`, `unsupported_type` (not HTML), `http_error`, `fetch_error`, `too_large`, `robots_disallowed`. A per-source table is printed at the end
- Safe to re-run: items that already have a record are skipped. With `--retry-failed`, a new record is appended and the latest one counts
- `--per-source N` takes the next N unfetched items from each source; `--limit N` caps the total
- Options: `--items`, `--feeds`, `--out`, `--html-dir` override the default paths
