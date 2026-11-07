# Where agents earn their keep

Review of the two proposed agent use cases, plus what's missing.

## Use case 1: source discovery ("initial URL analysis and planning")

**Agreed, with one adjustment: the agent comes *after* the probing, not in front of it.**

Plain code does the mechanical part (cheap, deterministic, same answer every time):
1. Normalize the URL (strip tracking params, resolve redirects, un-AMP, pick the canonical form).
2. Fetch the page (if reachable) and read `<link rel="alternate" type="application/rss+xml|atom+xml">`.
3. Probe common paths: `/feed`, `/feed.xml`, `/rss`, `/rss.xml`, `/atom.xml`, `/index.xml`, `/news/rss.xml`, `/blog/feed`.
4. Fetch `robots.txt` → `sitemap.xml` (handle `<sitemapindex>`; see [OpenAI](case-studies/openai-news.md)).
5. Record the evidence: status codes, content types, sizes, head tags, page structure hints.

The agent then makes **one decision from that evidence bundle** — a single model call, not a ten-turn browsing loop.

### What the agent is actually for here
- **Ambiguity:** several feeds exist (comments feed, category feed, main feed); which matches what the user meant?
- **Odd inputs:** a specific article instead of a blog, an AMP/mobile URL, a shortener, a PDF, a page behind login.
- **Non-website sources with feed equivalents:** YouTube channel, GitHub releases (`.atom`), subreddit, Mastodon, an email-only newsletter. Broad knowledge a hardcoded list doesn't have.
- **The stop condition:** "this source can't be monitored cheaply — use the browser, or ask the user."

### The key acceptance test
**Does the URL the user saved appear in the candidate feed/listing?**
Catches the most common wrong answer: a feed that exists but covers something other than what the user saved.

## Use case 2: self-healing

**Agreed, and it's the more valuable of the two — but the hard part is *detection*, not the fix.**

"We stopped receiving news" is the weakest possible trigger, and it is weakest exactly for rarely-updating blogs: a source that posts every two months is indistinguishable from a broken recipe for eight weeks.

### Health checks that don't depend on new content
| Check | Healthy | Broken |
|---|---|---|
| HTTP status | 200 | 403 / 404 / 5xx |
| Feed parses | Valid XML | Malformed |
| Item count | Stable (e.g. 10) | Suddenly 0 |
| Newest *known* post still present | Yes | Disappeared |
| Dates parse | Yes | No |
| Page fingerprint (size, shape) | Similar | Big change |

Silence becomes a **secondary** signal: warn when quiet for much longer than the source's own history (e.g. > 3× its median gap between posts).

### Failure taxonomy → response (most failures are NOT agent work)
| Failure | Response | Agent? |
|---|---|---|
| Timeout, 5xx | Retry with backoff | No |
| 403 / 429 (bot protection, rate limit) | Back off, slow down, consider browser fetcher | No |
| 301 / 404 — site moved or restructured | Re-run discovery | **Yes** |
| Feed parses but empty | Investigate | **Yes** |
| Extraction returns 0 items / unparseable dates | Re-derive recipe | **Yes** |
| Domain dead / blog discontinued | Notify user, pause source | No |

### Guardrails for the healer
- **Regression fixtures:** store the last N known posts per source. A new recipe is adopted **only if it reproduces them.** This blocks the dangerous failure: "fixing" a source by pointing it at the wrong feed and silently changing what the user follows.
- **Budget:** max repair attempts per source, cooldown between attempts, escalate to the user after repeated failure.
- **Versioned recipes:** keep history, allow rollback, log what changed and why.
- **Structured output:** the agent emits a **recipe** (small declarative config), not free-form actions. Auditable, replayable, cheap.
- **Untrusted input:** pages read during debugging may contain prompt injection. Page text is data; the recipe is validated by code before use.

## What was missing from the list

1. **Curation (biggest ongoing LLM value, and the part the user sees):** de-duplicate across sources, rank against interests, summarize, write the digest.
2. **Runtime extraction fallback:** for sources with no structured data, give the *extracted text* (not raw HTML — Anthropic's page was 89% script) to the model to list posts. Per-check cost, so restrict to the few sources that need it.
3. **Onboarding metadata:** estimate posting frequency (→ polling interval) and categorize the source for digest grouping.

## Why this shape holds: the economics
| Agent use | Frequency |
|---|---|
| Source discovery | Once per source |
| Self-healing | Once per breakage |
| Curation | Once per digest |
| Routine checking | **Never** |

No LLM cost scales with the number of checks. That's what makes watching ~100 sources daily affordable.
