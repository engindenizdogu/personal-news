# Project plan: EM 626 course project

A smaller, course-sized version of personal-news that tests the **recommendation** part of the product: can a graph model learn what one reader finds relevant from their ratings alone?

Course: EM 626 AI/ML for Systems (Stevens). Author: Engin Deniz Dogu (solo). Proposal: `docs/Project Proposal.docx`.

## Research question
Does graph structure improve relevance prediction over item text alone, using only the reader's ratings (no profile or personal information)?

## Scope
| In scope | Out of scope (stays in `docs/notes/` for the product) |
|---|---|
| 5–10 RSS/Atom feeds, chosen by hand | Websites without feeds, sitemap diffing, HTML listings, browser fallback |
| Historical backfill plus a daily re-fetch | Admission gate, probing, recipes, check intervals, health checks |
| LLM enrichment with code checks | Self-healing |
| Manual ratings in a small web form | Accounts, multiple users, email delivery |
| Graph models vs. non-graph baselines | Most of the security baseline (we only fetch feeds we picked) |
| A digest note grounded in model output | |

## Pipeline
`sources → collection → LLM enrichment → relevance model (graph) → digest`, with the reader's ratings closing the loop.

1. **Set sources:** 5–10 RSS/Atom feeds in `config/feeds.yml`.
2. **Collect (code):** fetch and parse with `feedparser`; normalize URLs; dedupe; append to `data/items.jsonl`.
3. **Enrich (LLM + code checks):**
   1. Free-form tags on all items → group into ~30 topics → freeze `config/topics.yml`.
   2. Per item: entities and 1–3 topics from the frozen list, plus post type, as JSON.
   3. Code checks: schema valid, topics in the list, entities appear in the item text, aliases merged. Invalid output: one retry, then fall back to no labels. Cache every output by input hash.
4. **Label (manual, runs alongside 3 and 5):** rating form with *more like this / neutral / show less*. Shows title, source and summary only (not LLM labels). Random order; timestamp every rating.
5. **Embed:** title + summary with a local `sentence-transformers` model. These vectors are the item features.
6. **Build the graph (code):** nodes are items, sources, entities, topics. Edges: `from` (item→source), `mentions` (item→entity), `about` (item→topic), optional `similar` (item↔item by embedding). Saved as PyG `HeteroData`, plus statistics (nodes, edges, degree distribution).
7. **Split:** by publish time into train / validation / test.
8. **Train:** graph models and baselines (below). Tune on validation only.
9. **Evaluate:** test set, 5+ seeds, mean ± std, ablations by edge type.
10. **Feedback:** a digest note for the reader and the system engineer, drafted by an LLM from the model's outputs only and checked claim by claim.
11. **Stretch:** LLM judge comparison; rerun on a slice of Microsoft's MIND dataset (also shows the multi-user case).

## Models and evaluation
- **Task:** node classification of items, 3-class and binary ("more like this" vs. rest).
- **Graph models:** GCN or GraphSAGE (baseline, required); HGT or TransformerConv with edge types (recommended). Attention weights for explanations.
- **Non-graph baselines:** logistic regression, random forest and gradient-boosted trees on the same item features; label propagation.
- **Metrics:** macro-F1 and PR-AUC (relevant items are rare). Report mean ± std over 5+ seeds.
- **Ablations:** with and without entity, topic and similar-story edges.
- **Leakage:** labels are human ratings. Item features never include the rating or anything derived from it. The topic list is built from item text only.

## Timeline
Today is Friday, November 6. Dates are Monday–Sunday weeks.

### Weekend setup: Sat Nov 7 – Sun Nov 8 (midterm prep)
- [x] Repo setup: `git init`, `uv` project, `.gitignore`, folder layout (see `CLAUDE.md`)
- [x] Pick 5–10 feeds; check how many items each feed exposes. 9 feeds in `config/feeds.yml`; Hacker News and Business Insider dropped, HackerNoon added
- [x] Fetcher → `data/items.jsonl` (`pnews.collect`). No separate backfill: history is what each feed exposes, filtered to items published since 2026-01-01 (`--since 2026`); Wayback backfill considered and not built
- [x] Article text with trafilatura → `data/content.jsonl` (`pnews.content`): sample of 5+ items per source for the midterm graph
- [x] Enrichment prompt, JSON schema and validator: entities on the content sample (free-form tagging and post types moved to week 1). 45 items, `z-ai/glm-5.3-flash` via OpenRouter, $0.016
- [x] Graph builder v0 and statistics (nodes, edges, degree distribution, a plot): `pnews.graph`, `report/tables/graph_v0_stats.md`, `report/figures/graph_v0_*.png`
- [x] Pipeline diagram (`report/midterm.md`)
- [x] Graph statistics notebook: centrality, source homophily, chi-square tests (`notebooks/graph_stats.ipynb`)
- [x] Status note: next steps, where labels come from, baselines, metrics (last slide of the midterm deck)

### Midterm presentation: Mon Nov 9
Deliverables required by the course:
- [x] Pipeline diagram (LLM components, graph construction, graph model, evaluation)
- [x] Preliminary LLM-generated components (fetcher, enrichment extractor)
- [x] First version of the graph (partial is fine) with basic statistics
- [x] Status note: next steps, label source, baselines, evaluation metrics. Presented: scale to ~25 sources and ~1,000 items; manual labels in 3 classes; GCN/GraphSAGE and TransformerConv vs. random forest and gradient-boosted trees; macro-F1 and PR-AUC on a time-based split, mean ± std over seeds

### Week 1: Nov 9 – Nov 15 (data and labels)
- [ ] Article text for all items (`pnews.content`); review coverage per source
- [ ] Free-form tagging; draft the topic list from the tags
- [ ] Post types: decide whether to keep them (item feature, not a graph node) and fix the closed list
- [ ] Freeze the topic list; re-run enrichment with it
- [ ] Rating form (Streamlit); start rating, target 150+ items by Sunday
- [ ] Daily fetch running
- [ ] Embeddings; graph builder v1 with features
- [ ] spaCy NER vs. LLM entities on a sample, for the validation log

### Week 2: Nov 16 – Nov 22 (baselines and first graph model)
- [ ] Time-based split
- [ ] Logistic regression, random forest, gradient-boosted trees, label propagation
- [ ] GCN / GraphSAGE; multi-seed runner
- [ ] Ratings: target 300+ items

### Week 3: Nov 23 – Nov 29 (Transformer model and ablations; Thanksgiving Nov 26)
- [ ] HGT or TransformerConv with edge types
- [ ] Ablations by edge type
- [ ] Attention-based explanations for a few items
- [ ] Ratings: all collected items rated

### Week 4: Nov 30 – Dec 6 (integration and feedback)
- [ ] Digest note with a grounding check
- [ ] One end-to-end script from raw feeds to final outputs. Development stays modular in `src/pnews/`; at the end, build one final file (notebook or bundled `.py`) that runs every stage and ships with `config/`, the enrichment cache and ratings. Confirm the expected format with the professor
- [ ] README with reproduction steps and fixed seeds
- [ ] Stretch, only if everything above is done: LLM judge (zero-shot)

### Buffer week: Dec 7 – Dec 13
- [ ] Report (~10 pages): design and key decisions, results with figures and metrics, limitations and threats to validity
- [ ] Appendices: prompts (with LLM and version), pipeline diagram, which components were LLM-generated vs. handwritten
- [ ] Slides
- [ ] Fresh-clone reproduction check

### Final presentation: Mon Dec 14

## Course deliverables checklist
- [ ] Pipeline design with data flow, module boundaries and validation steps
- [ ] LLM-generated components, with all prompts saved (LLM and version) in `prompts/`
- [ ] Report states which components were LLM-generated and which were written by hand
- [ ] Validation log: test inputs, expected vs. actual, fixes made (`VALIDATION_LOG.md`)
- [ ] Single script or notebook that runs end to end
- [ ] Fixed seeds and a README for reproduction
- [ ] Baseline GCN; Transformer-based comparison (accuracy/F1, training time, stability across seeds, interpretability)
- [ ] Non-graph baseline
- [ ] Train/validation/test split, several seeds, mean ± std
- [ ] Plain-English feedback grounded in model results
- [ ] Report (~10 pages) with prompts and pipeline diagram as appendices

## Risks
| Risk | Mitigation |
|---|---|
| **Too few items with 5–10 feeds.** Many feeds expose only 10–20 recent items | Prefer feeds with long histories or higher volume. Check counts during setup; if the total is under ~400 items, add feeds |
| Few relevant items; one rater | Macro-F1 and PR-AUC; discuss taste drift using rating timestamps |
| The graph doesn't beat the text baseline | A valid result; ablations and label propagation explain why |
| LLM variability | Closed topic list, schema checks, cached outputs, logged prompts and model versions |
| Rating takes longer than expected | Rate a little every day from week 1 |

## Ideas to explore
- **Jev for topic assignment** ([TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev)). A "System One" model that only returns values from a set of outputs defined in advance (up to 255 choices), with a calibrated probability for each. That fits step 3.2: assigning topics from the frozen list and post types from the closed set. Possible uses:
  - Use Jev in place of the OpenRouter LLM for topic and post-type assignment, or compare the two on a sample in `VALIDATION_LOG.md`.
  - Use its probabilities as `about` edge weights or as item features.
  
  It can't generate free text, so it can't do the free-form tagging (3.1), likely not open-ended entity extraction, and not the digest note; those stay with the OpenRouter LLM. Caveats: early access with a waitlist, and the claims in the post are self-reported. Request access early; don't put it on the critical path.

- **Persona labelling (suggestion, not the plan).** To speed up rating, an LLM with a written reader persona could label items. Manual labels stay the default. If used: a different model family from enrichment, a hand-labelled random sample with agreement reported (Cohen's κ), and the graph-vs-baseline result checked on the human-labelled subset. The claim would change to "a fixed persona's relevance", not a real reader's.

## Open questions
- Report due date: with the presentation on Dec 14, or later?
- ~~Commit data to git?~~ Decided Nov 7: commit `config/`, `data/items.jsonl`, ratings and the enrichment cache (feeds roll over, so a fresh clone cannot re-fetch history). Derived artifacts (embeddings, graphs, results) stay out.
