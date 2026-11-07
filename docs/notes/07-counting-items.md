# Counting items, and choosing how often to check

Question: to set a check interval we need a source's volume and window. How do we count its items? Doesn't every page mark up its content differently?

## Short answer
- **Feeds and sitemaps:** hardcodable. They're standards, so one parser covers every site.
- **HTML pages:** yes, every site differs. But we don't count by class names. We count by URL pattern, which the recipe already defines.
- **The rate doesn't have to come from the page at all.** It comes from our own history of when we first saw each item.

## Counting by method
| Method | What an item is | Dates from the source? | Per-site code? |
|---|---|---|---|
| RSS | `<item>` | `pubDate` | No |
| Atom (YouTube, many blogs) | `<entry>` | `published` / `updated` | No |
| JSON Feed | `items[]` | `date_published` | No |
| Sitemap diff | `<url><loc>` matching the recipe's prefix | **No**: `lastmod` is unreliable ([Anthropic](case-studies/anthropic-news.md), [OpenAI](case-studies/openai-news.md)) | No |
| HTML listing | Distinct links matching the recipe's URL pattern | Sometimes (`<time datetime>`, JSON-LD) | Only the pattern, stored in the recipe |

Feed quirks the parser must tolerate: items not in date order, some items without dates, `updated` vs `published` confusion, and feeds capped at a fixed length (WordPress defaults to 10; YouTube shows 15).

## HTML: count by URL pattern, not by markup
Class names are the fragile layer ([02](02-before-agents.md), [Anthropic](case-studies/anthropic-news.md): `PublicationList-module-scss-module__KxYrHG__date`). But article URLs follow a pattern that almost never changes, because changing it would break every inbound link and search result.

Anthropic's listing, counted this way: 11-12 distinct `href="/news/…"` links, no class names involved.

In order of preference, without per-site code:
1. **Semantic markup** when present: JSON-LD `ItemList` / `BlogPosting`, `<article>`, `<time datetime>`, microformats `h-entry`.
2. **The dominant URL pattern:** among all links on the listing, the largest group sharing a path shape (`/news/<slug>`, `/blog/2026/<slug>`). A general algorithm; no knowledge of the site.
3. **The model, once:** when neither works, it proposes the pattern, and it's stored in the recipe. If the count later drops to 0, that's a health-check failure that triggers self-healing.

## The rate comes from our own history
Every check records when each item was **first seen**. That's our clock, and it works for every method, including sitemap diffs and HTML listings with no dates.

Two numbers per source, both generic:
- **Capacity (N):** how many items one check can see. The feed length, or the number of links on the listing page.
- **Rate (r):** items per day, from first-seen timestamps over recent checks.

Then:
```
window   = N / r            # how long an item stays visible
interval ≤ window / 2       # check at least twice per window
```
Clamp the interval, for example between 1 hour and 7 days.

Examples from the case studies:
| Source | N | r (per day) | Window | Interval |
|---|---|---|---|---|
| NYT World | 57 | ~25 | ~2.3 days | ≤ ~1 day |
| NYT PersonalTech | 20 | ~0.3 | ~77 days | clamp to 7 days |
| YouTube channel | 15 | depends | 15 ÷ r | |
| Anthropic news listing | ~10 | measured | ~10 ÷ r | (sitemap diff has no window problem: it lists everything) |

## Cold start
Before any history exists:
- If the source has trustworthy dates (feeds), estimate `r` from them, as done for the NYT.
- Otherwise start at a conservative default (daily) and adapt as history builds up.

## The overlap check: the signal that we checked too rarely
Compare each check with the previous one:
- **Some overlap** (at least one item from last time is still visible): nothing was missed.
- **No overlap** (every visible item is new): the window turned over between checks, and items may have been lost. Halve the interval, and flag the gap.

This works for every source type, needs no dates, and is plain set logic. It's the correction that makes a wrong initial estimate harmless.
