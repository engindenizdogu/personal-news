# Landscape: products close to personal-news

Checked 2026-09-26 against each product's own site or docs. Features and limits change; re-check before relying on them.

## Headline
The space is **crowded**. "Follow sites without RSS" and "AI summaries of your feeds" both exist in mature products, and one (RSS.app) combines them into a delivered digest. Our difference has to come from **reliability and judgment**, not from the basic capability.

## Closest
| Product | Follows sites without feeds? | AI on top | Delivery | Notes |
|---|---|---|---|---|
| **RSS.app** | Yes: builds a feed from "virtually any website or social media channel"; point-and-click element selection | **AI Brief**: structured summary of a feed's articles; styles from Brief to Headlines-only | Slack, Discord, Telegram, email, on the feed's schedule | Closest to our product. AI Brief on paid plans, 5 AI credits/month included |
| **Feedly** | Yes: **RSS Builder** analyzes pages with lists of links (blog archives, news pages) and builds a feed | Summarizes every article, **deduplicates**, finds topics, mutes topics | In-app reader | RSS Builder on Pro+ (25 feeds) / Enterprise (100) |
| **Inoreader** | Yes: **Web feeds** suggest feed options from a pasted URL; also **Track changes** for pages | Summaries via prompts; transcripts and summaries for podcasts and YouTube | In-app reader | Web feeds and Track changes on Pro, with limits |
| **Readwise Reader** | Via RSS (not feedless sites) | Ghostreader: summarize, ask questions; auto-summaries for feed items need your own OpenAI key | In-app reader | Strong on newsletters, YouTube, PDFs, highlights; a reading app more than a monitor |

## Adjacent
| Product | What it does | Relation to us |
|---|---|---|
| **Visualping** | Page change monitoring with AI summaries | Watches pages, not streams of posts ([10](10-positioning.md)) |
| **Firecrawl** | Scraping API for developers | A possible component, not a competitor ([08](08-firecrawl.md)) |
| **changedetection.io** (open source) | Self-hosted page change monitoring | Visualping-like, self-hosted |
| **RSSHub, RSS-Bridge** (open source) | Community-written scrapers that turn sites into feeds | The "hand-written recipe per site" approach ([02](02-before-agents.md)) |
| **Kill the Newsletter** | Turns an email newsletter into a feed | The route for email-only newsletters |
| **FreshRSS, Miniflux, NetNewsWire** | Classic feed readers | Only sites that already have feeds |
| **ChatGPT tasks, Claude routines** | Scheduled AI prompts | Briefings from whatever the model finds, not tracking ([05](05-why-not-routines.md)) |

## Where we could genuinely differ
Only claims we can make once the personal version proves them. None of these products were checked for the absence of these features; "we do X" is a claim, "they don't" is not.
1. **Reliability as a feature:** health checks independent of new posts, silent-failure detection, validated self-repair.
2. **Pacing per source:** check intervals from each source's own history; volume budgets for firehoses.
3. **Digest-first, not reader-first:** Feedly, Inoreader and Readwise are apps you open; we deliver one digest.
4. **Choosing the method automatically:** feed → sitemap → embedded data → HTML → browser, instead of asking the user to select page elements.
5. **Publisher-respecting by design:** feeds and sitemaps first, never getting around blocks, headlines only where required.

## Next step: benchmark before building further
Run our case-study sources through RSS.app and Feedly (free tiers or trials) and compare:
| Source | Why it's a good test |
|---|---|
| anthropic.com/news | No feed; sitemap available |
| openai.com/news | Page blocked, feed available |
| nytimes.com | Blocked homepage, 57 section feeds, high volume |
| A YouTube channel | Feed via link tag |
| A rarely-updated blog | Tests "quiet vs broken" |

Questions: Does it find a working method? Does it notice when a source breaks? How noisy is the digest?

## Sources
- [RSS.app](https://rss.app/), [RSS Builder](https://rss.app/builder), [Meet AI Brief](https://rss.app/blog/meet-ai-brief-a-smarter-way-to-stay-on-top-of-information-zrYKid)
- [Feedly: follow websites that don't have RSS feeds](https://feedly.com/new-features/posts/easily-follow-websites-that-don-t-have-rss-feeds), [Feedly AI and Summarization](https://feedly.com/new-features/posts/feedly-ai-and-summarization), [RSS Builder docs](https://docs.feedly.com/category/592-rss-builder)
- [Inoreader: Improved Web feeds & Track changes](https://www.inoreader.com/blog/2025/02/improved-web-feeds-track-changes.html), [Inoreader pricing](https://www.inoreader.com/pricing)
- [Readwise Reader docs](https://docs.readwise.io/reader/docs), [Ghostreader FAQ](https://docs.readwise.io/reader/docs/faqs/ghostreader)
