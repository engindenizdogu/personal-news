# Code-generation log

Every prompt used to generate or substantially rewrite a component (course requirement).
Runtime prompts used by the pipeline (e.g. `enrich_v1.md`) are separate files in this folder.

## Components

| Component | Files | Origin | Notes |
|---|---|---|---|
| Project scaffolding | `pyproject.toml`, `.gitignore`, folder layout, `VALIDATION_LOG.md`, this file | LLM-generated | Setup only, no pipeline logic |
| Feed list | `config/feeds.yml` | Mixed | Feeds chosen by the author; file written by the LLM; Hacker News removed by the author |
| Fetcher (collect) | `src/pnews/collect.py`, `tests/test_collect.py`, pytest config in `pyproject.toml` | LLM-generated | Bug fix for feedparser date fallback after the author's test run |
| Content extractor | `src/pnews/content.py`, `tests/test_content.py` | LLM-generated | trafilatura on each item's link; not yet run by the author |

Origin is one of: LLM-generated, handwritten, mixed.

## Entries

### 2026-11-07 · Project scaffolding
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > Let's start setting up the project. Then we can start working on RSS feed collections.
- **Context given to the model:** `CLAUDE.md`, `PROJECT_PLAN.md`
- **Files produced:** `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `README.md`, `VALIDATION_LOG.md`, `prompts/codegen-log.md`, `config/feeds.yml` (empty stub), `src/pnews/__init__.py`, `src/pnews/models/__init__.py`, empty folders `app/`, `data/`, `report/`, `tests/`

### 2026-11-07 · Feed list and collection planning
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > You can add items.jsonl. Here are some RSS sources I found:
  > - https://openai.com/news/rss.xml
  > - https://blog.pragmaticengineer.com/rss/
  > - https://stripe.com/blog/feed.rss
  > - https://blog.cloudflare.com/rss/
  > - https://deepmind.google/blog/rss.xml
  > - https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml
  > - https://feeds.businessinsider.com/custom/all
  > - https://blog.codinghorror.com/rss/
  > - https://www.nature.com/nature.rss
  > - https://news.ycombinator.com/rss
  >
  > Save the list. Before you start building, let's plan. First, each feed has a different structure, does feedparser handle that? Second, not all feeds have the contents listed, some just have the links. For that we can send a get request to get the content. The problem after that is clearing the text. We could embed that into the LLM enrichment part. Are there other options for it?
- **Files produced:** `config/feeds.yml` (feed list), `.gitignore` (stop ignoring `data/items.jsonl`). A one-off probe script (not kept) checked each feed's format, item count, date range and text length.
- **Outcome:** feedparser covers all formats in use; text cleaning via `trafilatura` chosen over LLM cleaning (decided in the next prompt).

### 2026-11-07 · Fetcher (collect)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > Ok, I've looked at 'trafilatura'. I think it is a good option to start with. I've also removed hackernews from sources.
  > - First, build the fetcher. Once we have the fetcher and are able to save items in XML feeds, we'll filter them by date. I'll first inspect the results. Do not run the code, I'll inspect and run it then.
  > - Second, we will work on getting the content. Do not start this yet.
  >
  > (Note: I only asked you to stop recording prompts for the other chat, you can resume. Also, save the previous prompt. Do not save this part - the paranthesis)
- **Context given to the model:** `CLAUDE.md`, `PROJECT_PLAN.md`, `config/feeds.yml`, results of the feed probe
- **Files produced:** `src/pnews/collect.py`, `tests/test_collect.py`

### 2026-11-07 · Fetcher bug fix: feedparser `updated_parsed` fallback
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > One warning from feedparser:
  >   /Users/engindenizdogu/Desktop/local_repos/personal-news/.venv/lib/python3.12/site-packages/feedparser/util.py:95: DeprecationWarning: To avoid breaking existing software while fixing issue 310, a temporary mapping has been created from `updated_parsed` to `published_parsed` if `updated_parsed` doesn't exist. This fallback will be removed in a future version of feedparser.
- **Files changed:** `src/pnews/collect.py` (read date keys with `dict.get`), `tests/test_collect.py` (assert `updated_at is None` for a pubDate-only item), `pyproject.toml` (pytest fails on feedparser `DeprecationWarning`), `VALIDATION_LOG.md` (row for the bug)

### 2026-11-07 · Fetcher: `--since` date filter
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > Add an option to the collect command. We will filter by publish date. Filter if it is null and get items tha have a date >= 2026.
- **Files changed:** `src/pnews/collect.py` (`--since`, `parse_since`, `date_filter_reason`), `tests/test_collect.py` (two tests), `README.md`, `CLAUDE.md`

### 2026-11-07 · Content extractor (trafilatura) and item id order
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > - Start implementing trafilatura using links in the items.jsonl, create a new script for it.
  > - During collection, add an ID to the rows in items.jsonl so that we can match records when we are building the graph.
- **Context:** rows already had `item_id` (hash of the normalized URL) but `sort_keys` placed it mid-row.
- **Files produced/changed:** `src/pnews/content.py` (new), `tests/test_content.py` (new), `src/pnews/collect.py` (`item_id` written first; shared `http_get` helper with decompression and size cap), `tests/test_collect.py` (id-first check), `pyproject.toml`/`uv.lock` (`trafilatura`), `.gitignore` (`data/content.jsonl`), `README.md`, `CLAUDE.md`

### 2026-11-07 · Content extractor: per-source limit, null text on failure
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > - Do we write to a new file?
  > - Add a 'per source' flag to the script.
  > - I've also removed business insider from the source list.
  > - For links that the script cannot get the text, return null but stil add the row.
- **Files changed:** `src/pnews/content.py` (`--per-source N`, `--feeds`; skip sources not in `config/feeds.yml`; `text`/`words` null when no text), `tests/test_content.py` (null-text asserts, per-source and config-filter tests), `README.md`, `CLAUDE.md`

### 2026-11-07 · Plan update and commit
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`) via Claude Code
- **Prompt (verbatim):**
  > For now let's not focus on that. We now have 5 item content per source, that should be enough to begin working on the graph. Next week, we'll get more. We can also do the tagging part next week too. Update the plan and commit/push.
- **Files changed:** `PROJECT_PLAN.md` (ticked feeds, fetcher and content sample; tagging, topic list and post types moved to week 1; proposal file name), `.gitignore` (`.obsidian/`, Office lock files), `VALIDATION_LOG.md`
