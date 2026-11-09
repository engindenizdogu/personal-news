# personal-news (EM 626 course project)

A personal news digest that learns what one reader finds relevant from their ratings, using graph models.
Scope, pipeline and timeline: [`PROJECT_PLAN.md`](PROJECT_PLAN.md).

## Setup
Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned in `.python-version`.

```sh
uv sync                              # create .venv and install locked dependencies
cp .env.example .env                 # then fill in OPENROUTER_API_KEY (LLM enrichment and digest only)
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

### 3. Enrich: entities (LLM)
```sh
uv run python -m pnews.enrich --dry-run     # show the first inputs; no API calls, no files written
uv run python -m pnews.enrich --limit 5     # at most 5 API calls, to try it out
uv run python -m pnews.enrich               # every selected item not yet cached
```
- API key: `OPENROUTER_API_KEY` from `.env` in the repo root (git-ignored; template in `.env.example`). A variable already set in the shell takes precedence. `--env-file` points elsewhere
- Input: `data/items.jsonl` + `data/content.jsonl`. Items with a content record are used (article text; the feed summary when there is none). `--all-items` adds items without a content record. Only sources in `config/feeds.yml`
- Model and settings: `config/enrich.yml` (`z-ai/glm-5.3-flash` on OpenRouter, about $0.0004 per item; temperature 0, fixed seed, JSON mode, low reasoning effort, `max_tokens` 8000; only providers that honor all these parameters). Prompt: `prompts/entities_v1.md`. Article text is cut to 2,500 words. Each attempt stores the provider and `finish_reason`; an answer cut off at `max_tokens` counts as invalid
- Entity types: organization, person, product (any field, not only tech), location. Each entity has `entity_id` (`<type>:<normalized name>`), `name`, `type`, and `mention` (as written in the text)
- Checks in code: JSON and schema (one retry with the error, then no entities: `status: fallback`); each `mention` must appear in the input as a whole word, otherwise the entity is dropped and listed in `dropped`; names normalized (case, company suffixes, aliases in `config/entity_aliases.yml`) and duplicates merged
- Outputs (both committed): `data/enrichment/cache.jsonl`, the raw model answers keyed by input hash (model, prompt version, settings and messages); and `data/enrichment/entities.jsonl`, one validated row per item, rebuilt from the cache on every run
- Safe to re-run: a cached input is never sent again. Editing the checks or the alias table needs no new API calls. Changing the model or the prompt version creates new cache entries
- Requests are spaced 4 s apart (free models allow about 20 a minute) and rate-limit errors are retried with backoff

### 4. Graph
```sh
uv run python -m pnews.graph
```
- Input: `data/items.jsonl`, `data/enrichment/entities.jsonl`, `config/feeds.yml`; settings in `config/graph.yml` (version, layout seed, `min_entity_items`)
- Nodes: items (those with an enrichment row), sources, entities. Edges: `item -from-> source`, `item -mentions-> entity`, plus reverse edges. Node features in v0: one-hot source id, one-hot entity type; items carry their publish time (text embeddings come later)
- Outputs: `data/graphs/graph_<version>.pt` (PyG `HeteroData`, git-ignored) and `graph_<version>_nodes.json` (node index -> id); statistics in `report/tables/graph_<version>_stats.md` and `.json`; figures `report/figures/graph_<version>_degree.png` and `graph_<version>_network.png`
- Interactive browsing: `data/graphs/graph_<version>.gexf` (git-ignored) opens in [Gephi](https://gephi.org) or [Gephi Lite](https://gephi.org/gephi-lite/) in the browser. Every node and edge is included. Node attributes: `node_type`, `label` (item title, source or entity name), `source_id`, `entity_type`, `published_at`, `url`, `degree`; edges carry `relation` (`from`/`mentions`). Nodes come colored by type, sized by degree, with a seeded starting layout
- Deterministic: same inputs and config give the same graph and figures
- More statistics: `notebooks/graph_stats.ipynb` rebuilds the graph from the same inputs and adds edge densities, degree distributions, components and path lengths, the item–item projection, centrality (degree, betweenness, closeness, eigenvector, PageRank), a source-homophily permutation test, and chi-square tests (source × entity type, entity type × shared). Open it with the project's `.venv` kernel, or run it headless:

  ```bash
  uv run --with nbconvert jupyter nbconvert --to notebook --execute --inplace notebooks/graph_stats.ipynb
  ```
