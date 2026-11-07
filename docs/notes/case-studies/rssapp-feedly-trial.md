# Trial: RSS.app and Feedly (2026-09-26)

Hands-on impressions from the user, plus a check of the RSS.app feeds against the live sites.

## Feedly (user's impressions)
- Friendlier interface.
- Organized around **topics and curated "sources"**, not single URLs. No button to add one URL.
- Searching `https://openai.com/news/` suggested an "OpenAI" feed: a collection of OpenAI-related links, which did include the URL searched for, and posts from it were retrievable.
- No fine-grained control. Good for following an industry or topic, not a specific source.

## RSS.app (user's impressions)
- Very close to the original idea.
- **NYT failed**: it couldn't create a feed.
- Returns a feed URL per source. Also follows **keywords** and **social channels**.
- Scheduled "bots"/alerts (email, Telegram, …), feed bundles.
- Filters: auto-hide older posts, whitelist, blacklist.
- AI summary feature, also deliverable by email or message.
- Very customizable, sometimes overwhelming.
- Checks for broken links, but nothing that tells the user a source has gone **stale**.

## The feeds, checked against the live sites
| Feed | Items | Findings |
|---|---|---|
| Anthropic news | 4 (Sep 17–23) | The user had a **"hide posts older than 14 days" filter** on this feed, which explains the low count: the other posts on the live listing are older. Still, **one item is the listing page itself** (title "Newsroom", link `/news`) |
| OpenAI news | 25 (Aug 25–Sep 23) | All 25 are real posts. OpenAI's **official feed** (`/news/rss.xml`) has **74** items in the same window. The extra ones are partly categories the `/news` listing doesn't show ([OpenAI](openai-news.md)), but it means RSS.app scraped the page rather than using the site's own feed |
| Firecrawl blog | 25 (Aug 17–Sep 22) | Clean. A good test set for relevance (below) |
| YouTube @ycombinator | 25 | More than YouTube's own feed, which holds 15 |
| Topic: Artificial Intelligence | 25, all from one day | Aggregated news across outlets: a firehose |
| Keyword: "kebap" | 2, newest from July | Sparse |

Page-based feeds all stopped at 25 items; looks like a cap.

Takeaways:
- **The reliability gap is real**: a junk item (the listing page), a source where the official feed existed but wasn't used, and one (NYT) that failed while 57 official feeds exist. Our decision procedure would have found OpenAI's feed and offered the NYT's section feeds.
- Small sample, free usage. Worth re-running once ours works.

## Firecrawl blog: how much is signal?
The 25 titles, grouped by reading the titles only (a rough manual pass):
| Type | Count | Examples |
|---|---|---|
| **Company news** (funding, launches, partnerships) | 3 | "Introducing Alexandria and our $75M Series B", "Introducing Firecrawl Developer Index", "Firecrawl + Eden AI" |
| Product how-tos and customer stories | 3 | "How 11x Automates Prospect Research…", "…Convex App with Firecrawl" |
| "Best X in 2026" comparisons | 10 | "10 Best AI Voice Agent Platforms in 2026" |
| Generic explainers | 5 | "What Is Prompt Injection?", "AI for Content Marketing" |
| Generic how-tos and benchmarks | 4 | "How to Use a Coding Agent to Fix Production Bugs" |

Roughly **3 of 25** posts are the kind of news the user expected from *this* source.

**Clarification from the user:** this doesn't make the other posts bad. "AI for Content Marketing" could be useful, and from a source that is *about* marketing tools it would be exactly right. What matters is the content and **what the reader expects from each source**, not a fixed rule about post types.
