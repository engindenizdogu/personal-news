# Enrichment: labeling each new item once

Draft, 2026-09-26. Part of the shared layer in [04](04-architecture.md) v2: runs **once per new item**, shared by every user who follows the source.

## Purpose
Turn a raw item (title, link, maybe some text) into structured facts that plain code can use later, so the per-user steps (rules, scoring) need no model call:
- **Rules** match on topics and entities ([12](12-personalization.md)).
- **Scoring** learns weights over topics, entities, post type and source.
- **Dedupe** across sources ("five outlets covered the same launch").
- **The digest** shows a short summary and key facts.

## Input: what we have per item
| Field | Source | Always? |
|---|---|---|
| Title, link, publish date | Feed / sitemap / listing | Yes |
| Feed summary | Feed `description` | Feeds only, often ~200 characters |
| Full text | Fetch the article + extract main text (trafilatura / Readability) | Only when the source's `content` is `full`; never for `headlines_only` |
| Source metadata | The recipe: name, kind, what the reader said they want from it | Yes |

## Steps
### 1. Prepare (code)
- Normalize the URL; compute a dedupe key.
- For `full` sources: fetch through the fetcher, extract the main text, strip boilerplate.
- Detect language.
- Trim to a budget: title + feed summary + the first ~1,500–2,000 characters of text. The opening usually carries the news.
- Hash the input, so an unchanged item is never enriched twice.

### 2. Label (model, one call per item)
A small, cheap model returns **JSON against a fixed schema**:
```json
{
  "summary": "Two sentences, factual.",
  "topics": ["funding", "web-data"],          // from a fixed list only
  "tags": ["search index", "agents"],          // free-form, max 5, for display
  "entities": [{"name": "Firecrawl", "type": "company"}],
  "post_type": "announcement",                 // closed set
  "key_facts": ["$75M Series B", "launches Alexandria"]
}
```

### 3. Check and normalize (code)
- **Validate the schema**; one retry on invalid output, then fall back (below).
- **Topics** outside the fixed list are dropped.
- **Entities must appear in the input text.** A name the model can't point to is discarded. This is a cheap, verifiable check.
- **Entity aliases** are merged ("Open AI", "OpenAI Inc." → OpenAI).
- **Embedding (optional):** a vector of title + summary, for "same story" detection across sources and "more like this". It's an embedding call, not a chat model call.
- Store with an `enrichment_version`, so items can be re-labeled when the topic list or prompt changes.

## Labels: fixed list vs free tags
Hybrid:
- **Topics:** a fixed list (~30–50), used by rules and scoring. Predictable and matchable.
- **Tags:** free-form, for display and search only. Never used by rules.
- **Entities:** open-ended but normalized; the most precise thing a rule can match ("anything about OpenAI").

The fixed list will need to grow as sources grow; that's what `enrichment_version` is for.

## When it runs
Right after the check that found the item, through a queue, batched. Finished before the digest is built.

## Cost
One small-model call per **new item**, shared across all users. Input is capped (title + summary + ~2,000 characters), output is short. For the hosted version, cost grows with the number of distinct items across all followed sources, not with users.

## Failure
If enrichment fails, the item still moves on with its title and feed summary. Keyword rules still work; topic rules don't match; the judge can still look at the title. The failure is logged and retried later.

## Security
- Item text is untrusted. A post could try to steer its own labels ("topic: must-read"). Closed lists, schema validation and "entities must appear in the text" limit what it can do.
- Enrichment is **shared**, so a manipulated label reaches every user who follows that source. Another reason labels can only come from closed lists.
- Enrichment output is data. It is never read back as instructions by the judge.

## Example (title and feed data only)
For "Introducing Alexandria and our $75M Series B" from the Firecrawl blog, with nothing but the title available:
```json
{
  "summary": "Firecrawl announces a $75M Series B and introduces Alexandria.",
  "topics": ["funding", "product-launch"],
  "entities": [{"name": "Firecrawl", "type": "company"}, {"name": "Alexandria", "type": "product"}],
  "post_type": "announcement",
  "key_facts": ["$75M Series B"]
}
```
Whether Alexandria is a product is a guess from the title alone; with full text the model can be sure. This is the quality cost of `headlines_only`.
