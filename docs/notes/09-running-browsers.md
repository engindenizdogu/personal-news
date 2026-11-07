# Why running browsers at scale is hard

Memory and latency are part of it, but the harder problems are knowing when a page is done, keeping browsers healthy, and security.

## One page, two ways (measured 2026-09-26, anthropic.com/news)
| | Plain request (`curl`) | Real browser |
|---|---|---|
| Requests | 1 | 43, to 5 hosts |
| Data transferred | ~80 KB (compressed) | ~1.4 MB (3.2 MB decoded) |
| Time | ~0.19 s | `load` at 0.84 s, but requests kept arriving until **~6 s** |
| Memory | Negligible | 23 MB of JavaScript heap for this page alone; the browser's processes use much more |

Roughly **17× the data** and **30× the time** for a page whose posts were already in the plain HTML.

## The problems, from easiest to hardest
### 1. Resources
Every page runs a full rendering engine: CPU for scripts and layout, hundreds of MB per browser, several processes each. Concurrency is capped by RAM, so jobs queue. Mitigation: block images, fonts, media and ad/analytics requests. But blocking can break pages that depend on them.

### 2. "When is the page done?"
There's no clear end. Above, `load` fired at 0.84 s while requests continued for 6 s (analytics, lazy loading). Options are all heuristics:
- Wait for "network idle": can be too early (lazy content) or never happen (polling, live widgets).
- Fixed delay: slow and still unreliable.
- Wait for a condition: **best for us**. Reuse the recipe's URL pattern: done when at least N matching links are present, with a hard timeout.

Infinite scroll and "Load more" buttons add clicking and waiting on top.

### 3. Keeping browsers healthy
Long-running browsers leak memory, hang on some pages, crash, and leave orphaned processes. Needs: a hard timeout per page, a watchdog, and restarting the browser after N pages.

### 4. State between jobs
Cookies, local storage and cache persist unless reset. One source's cookies (or one user's) must never reach another's. Needs: a fresh browser context per job, which also enforces our "no cookies" rule.

### 5. Security (the big one for the hosted version)
A browser runs **untrusted JavaScript from arbitrary sites** on our servers.
- **SSRF from inside the page.** The page's own scripts, iframes and redirects can request `192.168.x.x`, `localhost` or the cloud metadata address. Our fetcher's SSRF guard never sees those requests. Every request the browser makes must be intercepted and checked, and the browser's network should be firewalled from internal services anyway.
- **Browser exploits.** Keep Chromium's sandbox on, run it in a locked-down container with no secrets in its environment, and update it promptly.
- **Downloads, popups, permission prompts:** disable them.

### 6. Operations
Browser binaries are hundreds of MB, versions change often, and headless browsers sometimes behave differently from normal ones. Debugging needs screenshots or traces, because "it returned nothing" doesn't say why.

### 7. Detection
Headless browsers are easier for bot protection to spot, so some sites fail. Services sell "stealth" to fix that. We won't: those sources fail, and admission tells the user why.

## What hosted services actually sell
Warm pools of browsers, recycling, isolation, and anti-bot handling, run by someone else. The first three are useful; the last is excluded by our policy.

## Our browser fallback, when we build it
- A queue with a small concurrency limit (1–2 for the personal version).
- A fresh context per job; no cookies.
- **Request interception applying the fetcher's SSRF guard to every browser request.**
- Block images, fonts, media, analytics.
- "Done" = the recipe's URL pattern matches at least N links; hard timeout.
- Restart the browser every N pages; watchdog for hangs.
- Record time, data and memory per render, to feed the build-vs-buy decision ([08](08-firecrawl.md)).
