# Project brief: personal-news

An agentic newsletter that watches sources the user has saved and delivers new items from them.

This page is the **implementation reference**: the decisions and rules in one place. The other notes hold the reasoning and evidence behind them.

## Thesis: clarity, not coverage
We're drowning in information. Readers like RSS.app and Feedly solve *collection*, but the reader still scrolls through hundreds of links. The goal here is the opposite: **find what is actually important and interesting to this reader**, and send little else. The product is closer to a personal editor than a reader.

What that means in practice:
- A small digest is success; a long one is failure. "Nothing important today" is a valid digest.
- Every shown item answers "why does this matter to me?"
- The same story from several sources appears once.
- Everything filtered out stays reachable, with a reason. Trust comes from never hiding things silently.
- Reliability underpins trust: a reader can only rely on a filter if they believe nothing was lost before it.

## Why
- There is too much content to keep up with by hand.
- Some sources (e.g. tech blogs) post rarely, so checking them manually is easy to forget and mostly wasted effort.
- Even with good tools, the reader still has to do the filtering.

## Two goals, equal weight
1. **Learning:** understand how AI agents browse the web.
2. **Shipping:** a working product. Third-party tools are fine where they help, as long as they follow the fetch policy.

## Decisions so far
| # | Question | Decision |
|---|----------|----------|
| 1 | What does a saved link represent? | A **source to follow** (not an example of taste) |
| 2 | Scope of discovery | **Only saved sources** for now (no finding new sources) |
| 3 | Learning path | **Build up through the web-access levels**, one module per level ([01](01-how-agents-access-the-web.md)) |
| 4 | Code yet? | Not yet. First milestone: the collection half plus the clarity test ([First milestone](#first-milestone-collection-and-clarity-test)) |
| 5 | Focus | Skim RSS; **focus on sites without feeds** ([Anthropic](case-studies/anthropic-news.md), [OpenAI](case-studies/openai-news.md)) |
| 6 | Source scope | **General** (blogs, newsletters, YouTube, releases, …), behind an admission gate. No tokens/passwords in URLs for now ([06](06-admitting-sources.md)) |
| 7 | High-volume sources | Allowed via their **feeds**, with a per-source volume budget; a site root prompts the user to pick sections. Sites that disallow AI agents are `headlines_only` ([NYT](case-studies/nytimes.md)) |
| 8 | Third-party fetchers (e.g. Firecrawl) | Allowed behind a single fetcher interface, for the sources that need them (JavaScript rendering, article extraction). **No automatic escalation on 401/403/429**; our admission and robots checks run before any call. **Build our own thin fetcher first** (trafilatura/Readability for article text, Playwright only when a real source needs JavaScript; all Apache-2.0, written from scratch, not forked). Firecrawl's hosted API (proxy pinned to `basic`) stays an optional second backend if measurements show many sources need rendering ([08](08-firecrawl.md)) |
| 9 | Publishing | **Goal: a hosted service for other users.** Start with a personal version in a **private repo** to test quality. Build with the hosted service's security needs from day one ([Security baseline](#security-baseline-build-now)) |
| 10 | Scale of a reader's list | A reader may save **hundreds of sources** and never has to prune them; curation is our job. Implications: rank across all sources, let consistently unhelpful sources sink on their own, bulk import (OPML, bookmarks), the "what do you want from this source?" question stays optional, and health problems are reported grouped and only when actionable. **Later:** multiple digests or source groups |

## First milestone: collection and clarity test
Build the collection half and use it to test the thesis before building personalization.

1. **Collection half:** admission, probe, recipes, scheduled checks, health checks, one fetcher with the security baseline. Enough to follow ~20 real sources reliably.
2. **Enrichment** of new items ([13](13-enrichment.md)).
3. **A daily clarity digest**, judged by the model from a short written profile plus an optional line per source ("what I want from it"). No learning yet.
4. **One week of use.** Each day the reader rates:
   - Did it save time compared to scrolling a reader app?
   - Was anything hidden that should have been shown?
   - Did something important reach you elsewhere first? ("I saw this elsewhere, why wasn't it here?")
5. **Decide:** if the week clearly beats scrolling, build learning and feedback ([12](12-personalization.md)). If not, find out why first.

Confirmed principles: per-reader curation of the reader's own sources is the point, and it's only practical with language models; misses the reader reports are a first-class trust signal; quiet days are allowed.

## Security baseline (build now)
The target is a hosted service where strangers submit URLs our servers fetch and read other people's digests. Some protections are cheap now and painful to retrofit, so they're part of the personal version too.

**Build now, even for one user:**
| Area | Rule | Why it's hard to add later |
|---|---|---|
| **SSRF** | The fetcher only connects to public IPs. Resolve DNS once and connect to that IP (prevents DNS rebinding); re-check on every redirect; limit redirects; `http`/`https` only | Every fetch path must go through it; one bypass is enough |
| **One fetcher** | All network access goes through a single fetcher: SSRF guard, robots.txt, per-host rate limits, timeouts, size caps, no cookies, no escalation | Scattered `fetch` calls are hard to find and fix later |
| **Browser requests** | If a browser is used, **every request the page makes** is intercepted and checked by the same SSRF guard; the browser runs sandboxed with no secrets in its environment ([09](09-running-browsers.md)) | A page's own scripts can reach internal addresses the fetcher never sees |
| **Data model** | Separate **feeds** (shared: one per endpoint, fetched once) from **subscriptions** (per user: which feeds, filters, budgets). Every user-owned row carries a `user_id`, even with one user | Splitting a single-user schema later means migrating all state |
| **Output escaping** | Titles, summaries and URLs from feeds are untrusted. Escape everything rendered in digests; allow only `http(s)` links | Feed content shown to other users is a stored-XSS path |
| **Prompt injection** | Page content is data. Model outputs are constrained (closed sets, schemas) and validated by code before use | Loosely structured model output spreads through the codebase |
| **Secrets** | API keys in environment variables or a secret store, never in the repo. `.gitignore` state and data from the start | Leaked keys in git history are permanent |
| **Logging** | No full URLs with query strings, no page bodies, no user identifiers in plain logs | Logs get copied and kept |
| **Cost accounting** | Record fetch credits and model tokens per user and per source | Needed for quotas; impossible to reconstruct afterwards |

**Later, before opening to others:**
- Accounts and authentication; per-user quotas (sources, checks, model spend); rate limits on adding sources.
- Abuse handling: users trying to make our fetcher hammer a site, probe internal networks, or fetch illegal content.
- Legal review of feed terms (e.g. NYT "personal, non-commercial use") and our own terms of service and privacy policy.
- Data deletion and export for users.
- License check of any open-source code we modify (AGPL: [08](08-firecrawl.md)).

## Core principle
**The model runs at the ends, never in the per-check loop.** Plain code does everything repeatable and verifiable; the model handles intent, outside knowledge and ambiguity ([03](03-where-agents-earn-their-keep.md), [career-ops](case-studies/career-ops.md)).

| Model call | How often |
|---|---|
| Choose a recipe (only when rules can't decide) | Once per source, often never |
| Self-heal a broken recipe | Once per breakage |
| Curate the digest | Once per digest |
| Routine checking | **Never** |

Rule for deciding who does what: **evidence → code; intent → the user; outside knowledge or ties → the model.**

## Pipeline
Full diagram: [04](04-architecture.md).

1. **Saved link:** the user adds a URL.
2. **Admit** (code): is it safe to fetch, and is it a publication? ([Admission rules](#admission-rules))
3. **Probe** (code): walk the [decision procedure](#decision-procedure-how-to-follow-a-source), collecting evidence.
4. **Choose the recipe** (code; model only on ties or when nothing passes).
5. **Validate** (code): the recipe must find the saved URL and reproduce known posts.
6. **Scheduled check** (code): run the recipe, normalize URLs, diff against the seen set.
7. **Health check** (code): detect breakage independently of new content.
8. **Self-heal** (model, only on real failures): propose a new recipe, which goes back through validation.
9. **Fetch and extract** (code): readable text for new items, unless `headlines_only`.
10. **Curate** (model): dedupe, rank, summarize a capped, prefiltered list.
11. **Deliver:** digest page or email.

## Decision procedure: how to follow a source
Try in order; stop at the first that passes validation. Cheapest and most stable first.

| # | Method | How it's found | Notes |
|---|---|---|---|
| 1 | **Feed** (RSS, Atom, JSON Feed) | `<link rel="alternate">` in the page head, then common paths (`/feed`, `/rss`, `/rss.xml`, `/atom.xml`, `/index.xml`, `/feed.xml`, `/news/rss.xml`), then a feed directory (e.g. `/rss`) | Standard format, one parser for all sites. Works for YouTube channels. Guessed paths still work when the page itself is blocked ([OpenAI](case-studies/openai-news.md)) |
| 2 | **Sitemap diff** | `robots.txt` → `Sitemap:` line, or `/sitemap.xml`. Handle `<sitemapindex>` | Diff URL sets under a path prefix. **Ignore `lastmod`**. Dedupe across child sitemaps ([Anthropic](case-studies/anthropic-news.md), [OpenAI](case-studies/openai-news.md)) |
| 3 | **Embedded data** | JSON-LD, `__NEXT_DATA__`/RSC payloads, a JSON API seen in the network tab | Clean data but undocumented; can change with any deploy |
| 4 | **HTML listing** | Links matching the dominant URL pattern (`/news/<slug>`) | **Never select by CSS class names**; count by URL pattern ([07](07-counting-items.md)) |
| 5 | **Browser** (headless) | Only for JavaScript-rendered pages, and only if the site allows automation | Heavy. Never to get past bot protection |

**Validation** (the gate for every method): the saved URL appears in the result, and the recipe reproduces the stored known posts. **Generate and test beats reason and decide**: with a cheap verifier, most sources are resolved with no model call.

## Admission rules
Details and examples: [06](06-admitting-sources.md).

Before any fetch (URL only):
- Scheme `https`/`http` only; no `user:pass@`.
- Host must resolve to a public IP. Re-check after every redirect.
- **Reject URLs that look like secrets:** `token`, `key`, `sig`, `signature`, `auth`, `X-Amz-*` parameters; `private-…` paths; share hosts (Google Calendar/Docs/Drive, Dropbox).
- **Never fetch action links:** `unsubscribe`, `confirm`, `verify`, `login`, `reset`, `activate`.
- Resolve shorteners with a redirect-only request, then re-check the final URL.

After fetching:
- `Content-Type` allowlist: HTML, RSS/Atom, XML, JSON. `text/calendar` → reject.
- Size cap, timeout, redirect limit.
- **Recognize non-content responses** ([NYT](case-studies/nytimes.md)):

| Response | Signals | Action |
|---|---|---|
| Bot-protection block | 403/429/503, tiny body, "enable JS / verify you're human", headers like `server: DataDome`, `cf-mitigated: challenge` | Don't get past it. Use feeds/sitemaps, or reject |
| Login page | 200 after redirect to a sign-in path, `return_to`/`continue`/`next` params, a password field | Reject: "requires sign-in" |
| JavaScript-rendered app | 200, app shell, big scripts, little text | Browser fallback, if allowed |

Shape and behavior:
- Items look like posts: distinct links, titles, **dates mostly in the past** (future dates → calendar/events).
- **Probation:** the first few checks are recorded but not delivered. Rotating pages (items replaced without growth) are rejected or treated as snapshots.
- The model classifies into a **closed set of kinds** only when rules can't decide. Default for anything unclear: **reject with a reason**, or ask the user.

Supported kinds (closed set): blog/newsletter (post), releases/changelog (version), video channel/podcast (episode). Calendar (announced event) possibly later.

## Fetch policy
- **Clean, cookieless session** for all fetching. The user's cookies are never used unless explicitly configured for one source.
- Identify honestly; honor `robots.txt`; per-host rate limits; conditional GET (`ETag`/`Last-Modified`) where offered.
- On 403/429: back off. **Never evade bot protection or CAPTCHAs.**
- If a site **disallows AI agents** in `robots.txt` or blocks automation: follow only its published feeds, in **`headlines_only`** mode (title, feed summary, link; no article fetch, no article text sent to a model).
- Respect feed terms (e.g. NYT: personal, non-commercial use). Revisit if the app ever serves other people.
- Blocked platforms (e.g. LinkedIn): only through what the user is entitled to, like data exports or email alerts ([career-ops](case-studies/career-ops.md)).
- Page content is **untrusted data, never instructions**, at every model call.

## Volume and check interval
Details: [07](07-counting-items.md), [NYT](case-studies/nytimes.md).

- Count items by method: `<item>`/`<entry>`/`items[]` for feeds, `<loc>` under the prefix for sitemaps, URL-pattern links for HTML.
- **Rate comes from our own first-seen history**, not from the page. Cold start: use feed dates if trustworthy, else check daily and adapt.
- `N` = items visible per check; `r` = new items per day.
  - `window = N / r`
  - `interval ≤ window / 2`, clamped (e.g. 1 hour to 7 days)
- **Overlap check:** if no item from the previous check is still visible, the window turned over: halve the interval and flag a possible gap.
- Volume classes: slow (<1/day, include all), steady (1–10/day, include all, grouped), firehose (>10/day, pick sections or filter, cap per digest).
- Budget items, not requests: fetching is cheap; tokens and attention aren't. Cap and prefilter before the model.
- Front-page feeds (e.g. NYT HomePage) are **snapshots**, not logs; prefer section feeds.

## Health checks and self-healing
Details: [03](03-where-agents-earn-their-keep.md).

Health signals that don't depend on new posts: HTTP status, parses, item count stable, newest known post still present, dates parse. Silence alarm at ~3× the source's median gap.

| Failure | Response |
|---|---|
| Timeout, 5xx | Retry with backoff (code) |
| 403, 429 | Back off, slow down (code) |
| 301/404, empty feed, 0 items, unparseable dates | Self-heal (model) → validation |
| Domain gone, blog discontinued | Tell the user, pause the source |

Rules (from [career-ops](case-studies/career-ops.md)): only a real 404 counts as a miss; throttles and network errors mean "unknown", never "dead". Also check *whose* content a source returns, not only *whether* it returns something.

Healer guardrails: a new recipe must reproduce the known-post fixtures; attempt budget and cooldown; versioned recipes with rollback; escalate to the user after repeated failure; never silently widen scope.

## Recipe format (draft)
The contract between code and model. The model may only propose values for these fields; code fills, validates and versions them.

```yaml
- name: NYT Technology                   # feed title → og:site_name → <title> → domain
  url: https://www.nytimes.com/section/technology   # what the user saved
  kind: blog                             # closed set: blog | releases | video | podcast
  method: feed                           # feed | sitemap_diff | embedded | html_links | browser
  endpoint: https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml   # must have returned 200 and parsed
  select: {}                             # sitemap_diff: {url_prefix}; html_links: {url_pattern}
  content: headlines_only                # full | headlines_only
  volume: {items_per_day: 5.7, window_days: 4.9}   # measured, re-measured over time
  interval_hours: 24                     # ≤ window / 2
  max_per_digest: 5
  fixtures: [...]                        # known posts from the first successful run
  enabled: true
  notes: ""
```

Who fills what ([04](04-architecture.md)): `endpoint`, `method` from the probe; `select`, `fixtures`, `volume`, `interval_hours` computed; `name` from metadata; `content` from the fetch policy; `enabled`, `notes`, section choices from the user. The model only breaks ties between passing candidates, handles unusual inputs, or proposes something when nothing passes.

## Files
| File | Layer | Holds |
|---|---|---|
| `sources.yml` | user | One recipe per source. Never rewritten by an update. In the hosted version this splits into shared **feeds** (recipe, state, health) and per-user **subscriptions** (filters, budgets); see [Security baseline](#security-baseline-build-now) |
| `state/` | derived | Seen URLs + first-seen times, known-post fixtures, health history, failure counters |
| `digests/` | output | What was sent, so nothing is sent twice |
| secrets store (later) | private | Tokenized URLs, if ever allowed; referenced by name, never logged, never sent to a model |

## Where it runs
Undecided. Scheduled AI runs (Claude routines, ChatGPT tasks) are fine for **model steps** like the daily digest, but not as the monitoring engine: stateless, capped, and they'd spend tokens on every empty check ([05](05-why-not-routines.md)). Monitoring is plain code triggered by cron, a routine, or a server.

## Open questions
- Delivery channel and cadence
- Where it runs (local cron, cloud routine, self-hosted)
- Language and stack
- Whether the digest is a static page, an email, or both

## Notes index
| Note | Topic |
|---|---|
| [01](01-how-agents-access-the-web.md) | The five levels of web access for agents |
| [02](02-before-agents.md) | How this was built before AI agents; the self-healing scraper |
| [03](03-where-agents-earn-their-keep.md) | Where the model is actually worth using |
| [04](04-architecture.md) | Architecture diagram and stage table |
| [05](05-why-not-routines.md) | Why Claude routines / ChatGPT tasks aren't the engine |
| [06](06-admitting-sources.md) | Admission: risky and non-publication URLs |
| [07](07-counting-items.md) | Counting items; check intervals from history |
| [08](08-firecrawl.md) | Firecrawl: where a hosted scraping API fits, and where it conflicts |
| [09](09-running-browsers.md) | Why browsers are expensive to run; rules for our browser fallback |
| [10](10-positioning.md) | How we answer "why not Firecrawl / Visualping?" |
| [11](11-landscape.md) | Products close to ours (RSS.app, Feedly, Inoreader, Readwise) and where we could differ |
| [12](12-personalization.md) | Brainstorm: learning what matters to each reader; post types; feedback |
| [13](13-enrichment.md) | Enrichment: labeling each new item once (topics, entities, summary) |

Case studies (`case-studies/`):
| Note | What it shows |
|---|---|
| [Anthropic](case-studies/anthropic-news.md) | No feed; sitemap diff; hashed class names |
| [OpenAI](case-studies/openai-news.md) | Bot-protected pages but open feed/sitemap; sitemap index; URL normalization |
| [NYT](case-studies/nytimes.md) | High-volume publisher; section feeds; bot-protection block vs JavaScript page; `headlines_only` |
| [career-ops](case-studies/career-ops.md) | A real system with zero-token scanning, providers, and bounded agent fallbacks |
| [ATS tokens](case-studies/ats-board-tokens.md) | Finding job-board slugs; generate-and-test in practice |
| [RSS.app & Feedly trial](case-studies/rssapp-feedly-trial.md) | Hands-on comparison; RSS.app feeds checked against the live sites |
