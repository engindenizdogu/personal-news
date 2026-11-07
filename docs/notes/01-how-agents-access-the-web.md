# How agents access the web

## The levels (cheap and reliable → flexible and expensive)
| Level | Technique | What the agent sees | Good at | Weak at |
|---|---|---|---|---|
| 1 | Structured data: RSS/Atom, sitemap.xml, site APIs | Clean records (title, date, URL) | Predictable, cheap, fast | Many sites don't offer it |
| 2 | Search APIs | Titles, URLs, snippets | Finding pages | Index lags; only snippets |
| 3 | Fetch + extract | HTML → markdown (often summarized by a small model) | Static pages, articles | No JavaScript; blocked by bot protection |
| 4 | Headless browser (Playwright/Puppeteer) | Page after scripts run, as HTML or accessibility tree | JS-heavy sites, clicking, scrolling | Slow, heavy, easier to detect |
| 5 | Computer use | Screenshots + mouse/keyboard | Anything a person can do | Slowest, most expensive, least reliable |

## Ideas that apply at every level
- **Representation is most of the work.** A raw page can be 100k+ tokens while the article is ~3k. Main-text extraction, the accessibility tree, and markdown conversion all exist to shrink that.
- **Agent loop:** look → decide → act → repeat. Every step costs time and tokens.
- **Web content is untrusted input.** Pages can contain prompt injection ("ignore your instructions…"). Treat page text as data, never as instructions.
- **Good citizenship:** robots.txt, terms of service, rate limits, bot protection, paywalls.
- **Non-determinism:** the same page can be read differently twice. Validate anything that must be exact (URLs, dates).

## Design rule for this project
Use an agent only where judgment is needed; use plain code everywhere else.
