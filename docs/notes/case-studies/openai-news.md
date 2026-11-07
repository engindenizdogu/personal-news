# Case study: openai.com/news (behind bot protection)

Investigated 2026-09-15 with `curl` and then the in-app browser (a real browser). Findings are a snapshot.

## Headline
Plain HTTP gets **403** on the listing page and on article pages (Cloudflare challenge: `cf-mitigated: challenge`, page says "Enable JavaScript and cookies to continue"). But the **sitemap and an RSS feed are not blocked**, and the feed covers almost everything.

## What plain HTTP (`curl`) can reach
| Resource | Status | Notes |
|---|---|---|
| `/news/` listing | ❌ 403 | Cloudflare JavaScript challenge |
| `/index/<slug>/` article pages | ❌ 403 | Same, so full article text needs a real browser |
| `/backend/articles/` (internal API) | ❌ 403 | Same |
| `/robots.txt` | ✅ 200 | `Allow: /`, points to sitemap |
| `/sitemap.xml` | ✅ 200 | Has `ETag` + `Last-Modified` |
| `/news/rss.xml` | ✅ 200 | **Found by guessing a common path**; ~725 KB; no `ETag`/`Last-Modified` |

## "The sitemap looks short": it's a sitemap index
- `/sitemap.xml` is only 3.4 KB because it's a **`<sitemapindex>`**: a list of **38 child sitemaps**, one per category (`company`, `research`, `product`, `engineering`, …).
- Together the children hold ~1,145 unique article URLs under `/index/`, plus other pages.
- Children total **~11 MB**, mostly `hreflang` alternates: **74,854 `<xhtml:link>` tags** (every article listed in ~65 languages). The URL data itself is tiny.
- **The same article appears in several category sitemaps** (174 URLs in 2 sitemaps, 27 in 3, 2 in 4). You must de-duplicate.
- **`lastmod` is useless for "new":** 199 URLs have today's date, 173 yesterday's. It reflects site rebuilds/edits.
- Article URLs are under `/index/`, not `/news/`. The listing page's path and the article path differ.

## The RSS feed
- 1,193 items, back to 2015. Fields: `title`, `link`, `guid`, `pubDate`, `category`, `description`.
- **Descriptions are short summaries** (max 683 chars), not full text.
- **Not in strict date order.** Sort by `pubDate` yourself.
- 161 items have no category.
- **URL normalization trap:** feed links have no trailing slash (`/index/fyxer`), sitemap URLs do (`/index/fyxer/`). A naive comparison matched **0**; after normalizing, **1,118** matched.
- Coverage vs sitemap: feed-only 7, sitemap-only 27. The newest 15 feed items were all in the sitemap.

## What the real browser showed (Level 4)
- The Cloudflare check **passed on its own**, with no puzzle. Real browsers look like real users; `curl` doesn't.
- **Feed autodiscovery works:** `<link rel="alternate" type="application/rss+xml" href="https://openai.com/news/rss.xml">` is in the page head. `curl` just never got to see it.
- No JSON-LD. Next.js with RSC payload.
- **Tailwind utility classes** (`text-nowrap text-primary-60`): these describe appearance, not meaning, so selectors built on them are fragile too.
- `<time datetime>` exists, but **formats are inconsistent**: `2026-09-11T10:00` (no time zone) vs `2026-09-10T09:00:00-07:00`.
- ~15 posts on first load, then a **"Load more" button** (no page-number links).

## The hidden API behind "Load more"
Clicking "Load more" and watching network requests revealed:
```
GET /backend/articles/?locale=en-US
    &pageQueries=[{"pageTypes":["Article"],"categories":["company","research","product",...]}]
    &limit=9&skip=9&sort=new
```
Response: `{ total: 603, items: [...], skip, limit }`, each item with `slug`, `title`, `publicationDate`, `categories`, `tags`, `seoFields`, …
- Clean JSON with pagination: the ideal data source.
- But **undocumented** (can change any time) and **blocked for plain HTTP** (only works inside a browser session).
- The listing's category filter explains why it shows fewer items (`total: 603`) than the feed (1,193). E.g. the newest feed item (a customer story, Sep 14) isn't among the listing's categories.

## Ways to detect new posts here, ranked
| Approach | Reachable with plain HTTP? | Stability | Notes |
|---|---|---|---|
| **RSS feed** | ✅ | High (public, linked from page head) | Best choice. Sort by date, normalize URLs |
| **Sitemap index diff** | ✅ | High | Good backstop; fetch 38 children, de-duplicate, ignore `lastmod`. Heavy (~11 MB) |
| **Internal JSON API** | ❌ browser only | Low-medium (undocumented) | Great data, but needs a browser session |
| **Listing HTML** | ❌ browser only | Low (Tailwind classes) | No reason to use it here |

## Lessons
1. **Access and interpretation are separate problems.** Here the problem is access. An LLM can't help read a page it can't get.
2. **Bot protection often guards pages, not feeds/sitemaps.** Always try those before reaching for a browser.
3. **Feed discovery has three steps:** `<link rel="alternate">` in the page → guess common paths → sitemap. When the page is blocked, step 2 still works.
4. **Normalize URLs** (trailing slash, query strings, `http`/`https`, `www`) before comparing sets.
5. **Browser DevTools' Network tab is a discovery tool.** "Load more" and infinite scroll usually call a JSON API.
6. **Respect the signal.** A challenge means "we don't want automated access here." The app should use what the site openly publishes (feed, sitemap), not try to get around protection.

## Anthropic vs OpenAI
| | anthropic.com/news | openai.com/news |
|---|---|---|
| RSS | ❌ none | ✅ `/news/rss.xml` |
| Plain HTTP to pages | ✅ | ❌ Cloudflare challenge |
| Sitemap | Single file, 257 news URLs | Index of 38 files, duplicates across them |
| `lastmod` trustworthy? | ❌ | ❌ |
| Listing pagination | "See more" | "Load more" → JSON API |
| Class names | Hashed CSS Modules | Tailwind utilities |
| Best method | Sitemap URL diff | RSS feed |
