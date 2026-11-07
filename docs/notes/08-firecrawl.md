# Firecrawl: where it would fit

Checked against Firecrawl's docs and pricing on 2026-09-26. Details change; re-check before relying on them.

## What it is
A hosted web-data API aimed at AI apps:
- **`/scrape`**: one URL → markdown, HTML, JSON matching a schema you give, or a screenshot. Renders JavaScript.
- **`/crawl`**: follow links across a site or section, with depth, page limits and path filters.
- **`/map`**: list a site's URLs (up to 100k results).
- **Search**, and **interact** (drive a browser).
- **Change tracking**: each scrape stores a snapshot and compares it with the previous one for that URL: new, unchanged, modified, or removed. Snapshots don't expire; basic and git-diff modes cost nothing extra.
- **Proxies:** basic and **enhanced**. Enhanced is "for scraping sites with advanced anti-bot solutions". In `auto` mode, a **401, 403 or 429 triggers a retry through enhanced proxies**.
- **Pricing:** 1 credit per page for scrape, crawl, map and monitor; 1,000 free credits a month; paid plans for more.
- **Robots:** `/crawl` respects `robots.txt` rules for `FirecrawlAgent`. I didn't find a clear statement for `/scrape`.

## Mapped onto our design
| Our piece | Firecrawl equivalent | Fit |
|---|---|---|
| Level 3: fetch + extract | `/scrape` → markdown | Good: exactly the "readable text, not raw HTML" step |
| Level 4: headless browser | JavaScript rendering, interact | Good: saves running Playwright ourselves |
| Embedded data / HTML listing | `/scrape` with a JSON schema | Useful for the model fallback, but it's a model call per page, so onboarding only |
| Sitemap diff | `/map` | We already do this with one sitemap request |
| Level 1: feeds | Nothing | Not needed: feeds are one plain request |
| Change detection | Change tracking | **Different unit**: it diffs *pages*; we diff *items* |
| Admission, validation, health, recipes, curation | Nothing | Still ours |

## Where it conflicts with our rules
1. **Proxy escalation on 403/429.** `auto` mode does exactly what the fetch policy forbids: treat a block as a reason to try harder. The NYT homepage (DataDome 403, robots disallowing AI agents) is the case it's built to push through. If used, **pin proxies to basic and treat 403/429 as final.**
2. **Page diffs aren't item diffs.** A listing page "changes" when an ad, a "trending" box or a timestamp changes. We still need our seen-URL set and first-seen history for new items, rates and the overlap check.
3. **Per-check cost comes back.** 1 credit per page per check. Following 20 feedless sources daily is ~600 credits a month: inside the free tier, but it scales with checks, not with new posts. Using it for feed sources would be pure waste.
4. **Another party sees every URL.** Admission already rejects tokenized URLs, so this is acceptable, but it's one more reason to keep that rule.
5. ~~It hides what we're learning.~~ Goals updated 2026-09-26: shipping the product counts as much as learning, so this isn't a reason to avoid it.

## Is it costly? Depends entirely on how it's used
Plans checked 2026-09-26: Free 1,000 credits/month; Hobby $19/month (5,000 credits); overage in $5 increments (1,000 credits on Hobby). Higher-tier prices not verified.

Estimate for a personal setup with 50 sources:

| Usage pattern | Credits/month | Rough cost |
|---|---|---|
| **Narrow:** only JavaScript-only sources (say 5, daily) + article text for ~15 new items/day + onboarding | ~600–850 | Free tier |
| **All sources through Firecrawl, daily** | ~1,500 | Hobby, $19 |
| **All sources through Firecrawl, hourly** | ~36,000 | ~$175 on Hobby with overage |

Cheap as a specialist, expensive as the general fetcher. The narrow case can shrink further: most blog articles are server-rendered, so a free local extractor (trafilatura, Readability) handles them, leaving Firecrawl only the JavaScript pages.

## Escalation, in detail
The mechanism, per the docs:
1. A scrape request goes out through a **basic** proxy.
2. The site answers **401, 403 or 429**.
3. Firecrawl reads that as "the proxy wasn't good enough" and **retries the same URL through enhanced proxies**, which exist for "sites with advanced anti-bot solutions".
4. 404 and 5xx don't escalate. The retry costs no extra credit.

What those codes actually mean:
| Code | Meaning | Correct response | What escalation does |
|---|---|---|---|
| 401 | Authentication required | Stop: you need credentials | Retries anyway; a different IP doesn't add credentials |
| 403 | Forbidden, often a bot-protection block | Respect it; use feeds/sitemaps | Retries from infrastructure built to look less like a bot |
| 429 | Too many requests | Slow down; honor `Retry-After` | Retries immediately from elsewhere: rate-limit evasion |

Why this matters for us:
- **It turns a "no" into "try from somewhere they won't recognize."** For the NYT homepage (DataDome block, robots disallowing AI agents), that's precisely the gate we decided to respect ([NYT](case-studies/nytimes.md)).
- **It hides the signal.** The call just succeeds. Our health checks and fetch policy depend on seeing 403/429; with escalation, "blocked" and "fine" look the same.
- **It's the default.** If you don't pass `proxy`, it's `auto`.
- **The opt-out is deprecated.** The docs mark the `proxy` parameter as deprecated and recommend leaving it on `auto`. Today we can pin `basic`; that may stop working. So "just configure it" isn't a durable safeguard.

Mitigations if we use the hosted service:
- Pin `proxy: basic` while it exists, and watch the changelog.
- **Check robots.txt and our admission rules ourselves before calling it.** Never send it a URL our policy wouldn't fetch.
- Only send it sources already known to allow automation.

**Self-hosting sidesteps the problem.** Firecrawl is open source (AGPL-3.0), and self-hosted instances **don't include Fire-engine**, the closed component that handles IP blocks and bot detection. What remains is basic fetching + Playwright + markdown conversion: the parts we want, without escalation, and without per-credit cost. Costs: running it (Docker, a browser service) and the AGPL terms, which matter only if we ever serve it to others.

## What the AGPL means for us
Not legal advice; a working summary.

- **GPL** obligations are triggered by *distributing* the software. Running it on a server and letting people use it over the web isn't distribution, so a GPL web service never has to share its source (the "SaaS loophole").
- **AGPL** closes that gap with **section 13**: *if you modify the program*, your modified version must offer its source to **all users interacting with it remotely over a network**.

| Scenario | Obligation |
|---|---|
| Hosted Firecrawl API (their servers) | None from the AGPL. Their terms of service apply instead |
| Self-hosted, only you use personal-news | None. You're the only user |
| Self-hosted, **unmodified**, others use personal-news | Section 13 applies to modified versions, so none in practice |
| Self-hosted, **modified**, others use personal-news | Likely publish **the modified Firecrawl's** source. Whether users "interact with" a backend they only reach through our app is debated; publishing the fork is the safe choice. Our own app's code stays ours |
| **Copying Firecrawl code into our app** | Our app becomes a derivative work → **our whole app** is AGPL, and its source must be offered to its users |

Keeping Firecrawl as a separate service, called over HTTP or through its MIT-licensed SDKs, keeps our code independent. That's one more reason for the fetcher interface.

## Build our own vs the free tier (decided 2026-09-26)
What we'd actually use from Firecrawl is two things: **HTML → clean article text**, and **rendering JavaScript pages**. Both exist as permissively licensed libraries (checked on GitHub, 2026-09-26):

| Need | Library | License |
|---|---|---|
| Article text from HTML | trafilatura (Python) | Apache-2.0 |
| Article text from HTML | Mozilla Readability (JS) | Apache-2.0 |
| JavaScript rendering | Playwright | Apache-2.0 |
| (for comparison) | Firecrawl | AGPL-3.0 |

Firecrawl's hard-to-replicate value is **managed browsers at scale plus anti-bot handling**, and anti-bot handling is the part our policy excludes.

**How often do we need JavaScript rendering?** In every case study so far, never for monitoring: Anthropic is server-rendered, OpenAI and NYT are blocked but have feeds, YouTube has feeds, and most job boards (career-ops) have public APIs.

**Decision: build our own thin fetcher; don't adopt the free tier now.**
- Extraction: a library call, small work. No per-page cost, no third party seeing URLs.
- JavaScript rendering: add Playwright only when a real source needs it. For the hosted version, a browser loading untrusted pages must run isolated (sandboxed container, no network access to internal services).
- Written from scratch, not forked: AGPL doesn't apply. Reading Firecrawl's docs for ideas is fine; copying its code is not.
- **Measure:** log which sources fail without JavaScript rendering. If many do, add Firecrawl (hosted, `proxy: basic`) as a second backend behind the same fetcher interface.

Why not the free tier first: 1,000 credits fits the personal version, but it's a dependency for the core extraction step, its default escalates on 401/403/429 with a deprecated opt-out, every URL goes to a third party, and for the hosted goal costs grow with articles fetched.

## Recommendation
- Build the levels ourselves first, as planned.
- Put all fetching behind one **fetcher interface**: `fetch(url, mode) → {status, headers, body}`. A Firecrawl-backed fetcher can be added later for the few sources that need JavaScript rendering, with enhanced proxies off.
- Use it where it's strongest: turning an article page into clean markdown, and rendering JavaScript pages that allow automation.
- Keep feeds, sitemaps, item diffing, admission and validation in our own code.

## Sources
- [Firecrawl](https://www.firecrawl.dev/)
- [Change Tracking — Firecrawl Docs](https://docs.firecrawl.dev/features/change-tracking)
- [Enhanced Mode — Firecrawl Docs](https://docs.firecrawl.dev/features/enhanced-mode)
- [Pricing — Firecrawl](https://www.firecrawl.dev/pricing)
- [Crawl — Firecrawl](https://www.firecrawl.dev/crawl)
