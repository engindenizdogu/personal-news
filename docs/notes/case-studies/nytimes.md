# Case study: nytimes.com (a high-volume publisher)

Investigated 2026-09-26 with plain `curl`. Snapshot; the site and its rules can change.

## What the site offers
| Resource | Result |
|---|---|
| Homepage `www.nytimes.com/` | **403**, `server: DataDome` (bot protection). 771-byte block page |
| `www.nytimes.com/robots.txt` | 69 user-agent groups. **`Disallow: /` for AI agents**, including `anthropic-ai`, `ClaudeBot`, `Claude-User`, `Claude-SearchBot`, `GPTBot`, `ChatGPT-User`, and scraping tools like `Scrapy`, `news-please` |
| RSS directory `www.nytimes.com/rss` | 200. Lists **57 section feeds** on `rss.nytimes.com` |
| RSS terms (on that page) | Feeds allowed *"for personal use in a news reader or as part of a non-commercial blog"*; commercial use needs written permission |
| Feeds on `rss.nytimes.com` | 200, reachable with plain requests. No `ETag`/`Last-Modified`. `rss.nytimes.com/robots.txt` is 404 |

Feeds include: Africa, Americas, Arts, AsiaPacific, Business, Climate, Dealbook, Economy, Education, Europe, Health, HomePage, MiddleEast, MostEmailed/Shared/Viewed, Movies, NYRegion, PersonalTech, Politics, Science, Space, Sports (and many sports), Technology, Upshot, US, Well, World, YourMoney, …

## Measured volume
From each feed's own `pubDate`s:

| Feed | Items | Time span | ≈ Items/day |
|---|---|---|---|
| World | 57 | 2.3 days | 24.8 |
| HomePage | 14 | 0.7 days | 19.2 |
| Business | 49 | 2.8 days | 17.6 |
| Science | 34 | 5.9 days | 5.8 |
| Technology | 28 | 4.9 days | 5.7 |
| Climate | 52 | 28.5 days | 1.8 |
| PersonalTech | 20 | 77.4 days | 0.3 |

Descriptions are short (max ~200 characters): headlines and summaries, not article text.

A ~80× range between two feeds from the same publisher. "Follow the NYT" isn't one decision.

## Where the waste actually is
Fetching isn't the cost. One feed is tens of KB; checking it hourly is negligible.

The cost is downstream, and it scales with **items per day**:
- **Article fetching:** 25/day from World alone. And here it's blocked anyway (DataDome, paywall, robots).
- **Model tokens:** curation reads every candidate.
- **The reader's attention:** the scarcest resource. A digest with 60 NYT headlines is a failed digest.

So the right control is a **volume budget per source**, not "don't follow busy sites."

## How to handle it
### 1. A site root becomes a choice, not a subscription
Saving `nytimes.com` shouldn't mean "follow everything." Admission sees a large publisher with a feed directory and asks:
> The New York Times publishes ~150 items a day across 57 sections. Which sections? (Technology · Science · Climate · …)

This is intent, so the user answers it ([03](../03-where-agents-earn-their-keep.md) rule: evidence → code, intent → user). Discovering the directory is evidence: the `/rss` page, feed link tags, or a sitemap.

### 2. Measure volume at admission
Compute items/day and the feed's **window** (how far back it reaches) from the feed itself, as above. Classify:

| Class | Items/day | Default handling |
|---|---|---|
| Slow | < 1 | Everything goes in the digest |
| Steady | 1–10 | Everything, grouped |
| Firehose | > 10 | Ask for sections or a topic filter; cap per digest |

### 3. Check interval comes from the window, not the volume
To not lose items, check more often than the window turns over: **interval ≤ window ÷ 2**.
- World (2.3-day window): daily is safe.
- PersonalTech (77-day window): weekly is plenty.
- HomePage (0.7-day window): would need checks every ~8 hours. But HomePage is a *front page*: a rotating selection of what's prominent now, not an archive. Missing items is fine. It's a snapshot source, not a publication log. Probation ([06](../06-admitting-sources.md)) would flag it as churning.

### 4. Budget per source, before the model
- `max_per_digest`: take the top N per source.
- Keyword or topic filter in code, before curation.
- Cross-source dedupe: a World story will often also appear elsewhere.

The model ranks a capped, prefiltered list, not the raw firehose.

### 5. Respect the publisher's terms
- **Feeds: yes.** Explicitly allowed for personal use in a news reader, which is what personal-news is.
- **Article pages: no.** Bot-protected, paywalled, and robots disallows AI agents, including user-initiated ones (`Claude-User`, `ChatGPT-User`).
- **So NYT sources are `headlines_only`:** title + feed summary + link out. No article fetching, and no article text sent to a model. Ranking and grouping use the headline and summary.
- If personal-news ever served other people, the "personal, non-commercial" condition would need revisiting.

General rule: when robots disallows AI agents or the site blocks automated access, a source can still be followed through its published feed, but in `headlines_only` mode.

## "Please enable JS and disable any ad blocker" is a block, not a JavaScript page
That's the whole body of the homepage response to a plain `GET`: 771 bytes, status **403**, `server: DataDome`, and a script from DataDome's CAPTCHA service (`geo.captcha…` / `ct.captcha…`). The message says "enable JS", but the page isn't rendered by JavaScript. It's a checkpoint deciding whether the visitor is a person.

Three things that look alike from a plain request:
| | Status | Body | What it means | Route |
|---|---|---|---|---|
| **JavaScript-rendered site** | 200 | An app shell: a big script bundle, little text | Content is built in the browser | Browser fallback (Level 4), if the site allows automation |
| **Bot-protection challenge** | 403 (sometimes 429/503) | Tiny page, "enable JS / verify you are human", challenge script; headers like `server: DataDome`, `cf-mitigated: challenge` | The site is deciding whether to let automation in | **Don't try to get past it.** Use the site's feeds/sitemaps, or drop the source |
| **Login / paywall** | 200 after redirect, or 401/403 | Sign-in page or paywall | Needs an account | Sources the user is entitled to only ([06](../06-admitting-sources.md)) |

All three are detectable in code from status, headers and body size, so none of them needs the model to recognize it.

For the NYT specifically, a browser would also be the wrong tool on principle: robots.txt disallows AI agents by name, including user-initiated ones (`Claude-User`, `ChatGPT-User`). A real browser might pass the challenge the way it did for OpenAI ([OpenAI](openai-news.md)), but that would be getting around a gate the site put there on purpose. The feeds make it unnecessary anyway.

## Recipe example
```yaml
- name: NYT Technology
  url: https://www.nytimes.com/section/technology
  method: feed
  endpoint: https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml
  volume: {items_per_day: 5.7, window_days: 4.9}   # measured, re-measured over time
  interval_hours: 24                                # ≤ window / 2
  content: headlines_only                           # no article fetch, no body to the model
  max_per_digest: 5
```

## Takeaways
1. **Volume is a property of a feed, not of a site.** Measure it; don't guess from the brand.
2. **Fetching is cheap; attention and tokens aren't.** Budget items, not requests.
3. **The window sets the check interval.** Volume sets the digest budget.
4. **Front pages are snapshots, not logs.** Treat them differently, or steer the user to section feeds.
5. **What a site publishes as a feed and what it lets automated agents fetch can differ.** Honor both: use the feed, don't scrape the pages.
