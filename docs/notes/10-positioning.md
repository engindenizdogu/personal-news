# Positioning: how we answer "why not X?"

Draft answers, written to be said to a person. Competitor details were checked on 2026-09-26; re-check before using them publicly.

**Before saying these to real users:** several claims (health checks, self-repair, per-source pacing) are designs, not features yet. The personal version has to prove them first. That list doubles as a checklist for "good enough to publish."

## Summary
| | What it watches | Unit of change | Best for |
|---|---|---|---|
| **Firecrawl** | Any URL, on request | A page's content | Developers who need page content or structured data |
| **Visualping** | A page, or part of one | A page changed | Prices, policies, stock, notices: pages without a stream of posts |
| **personal-news** | Sources you follow | A new post | Blogs, channels, newsletters, releases |

---

## "Why not Firecrawl?"

"They're different kinds of tools, so it's less 'instead of' and more 'what are you trying to do.'

**Firecrawl is infrastructure for developers.** You give it a URL, it gives you the page's content as clean markdown or structured data. It's very good at that, including crawling whole sites and handling heavy JavaScript. What you do with the content is up to you.

**Personal-news is for readers.** You give it the blogs, channels and newsletters you care about, and it tells you what's new in them, in one digest. You never deal with pages, markdown or APIs.

The difference shows up in the things a scraping API doesn't do for you:

- **It knows what a new post is, not just that a page changed.** A page changes when an ad rotates or a 'trending' box updates. We track the posts themselves, so you're told about the new article, not a diff.
- **It picks the right way to follow each source.** A feed if there is one, the sitemap if not, the page itself as a last resort. That makes it cheap to check often and hard to break when a site redesigns.
- **It tells you when a source breaks.** A blog that posts twice a year and a blog whose feed quietly died look the same from the outside. We check each source's health separately from whether it posted, and fix the broken ones or tell you, instead of going silent.
- **It paces itself to each source.** The blog that posts twice a year never gets forgotten, and a newspaper that publishes 150 things a day doesn't flood your inbox. You pick sections, and it caps what gets through.
- **It gives you a digest, not a pile.** Duplicates across sources are merged, and the rest is ranked and summarized.
- **It plays fair with publishers.** It uses what sites openly publish and never gets around their blocks. Where a site allows only headlines, you get headlines and a link. It also never uses your logins or cookies.

If you're a developer who needs raw page content, whole-site crawls, or data pulled from sites that don't want to be scraped, use Firecrawl. We don't do that, on purpose.

If you just want to stop missing things from the sources you follow, that's what we built."

Background: [08](08-firecrawl.md).

---

## "Why not Visualping?"

"Visualping watches **pages**. We watch **publications**.

Visualping is excellent at 'tell me when this page changes.' You pick a page, or draw a box around part of it, and it checks on a schedule. When something changes, it sends you an alert with an AI summary of what changed. That's exactly right for a pricing page, a terms-of-service page, a product that's out of stock, or a government notice.

A blog, a YouTube channel or a newsletter isn't really a page that changes, though. It's a stream of posts. That's what we're built for, and it changes a few things:

- **Less noise to filter.** A page changes for lots of reasons: an ad rotates, a 'trending' box updates, a date ticks over. Visualping handles that with AI that judges each change, and by their own numbers it rates 83% of the changes it detects as not important. We track the posts themselves, so a rotating banner never looks like news in the first place.
- **One digest, not an alert per page.** You get one summary across everything you follow, with the same story from five sources merged into one.
- **It scales to how people actually read.** Following 50 blogs is normal. With per-page, per-check pricing, that adds up fast: Visualping's $10 plan covers 10 pages and 1,000 checks a month. We follow most sources through their feeds, which costs almost nothing to check, so following 50 sources doesn't cost 50 monitors.
- **It paces itself to each source.** A blog that posts twice a year and a newspaper that posts 150 times a day need very different handling. We check each at a rate that matches its own history, and cap what the busy ones can send you.
- **It tells you when a source breaks.** From the outside, a quiet blog and a broken one look the same. We check each source's health separately, so silence means 'nothing new', not 'something died'.

If you want to know when a particular page changes, like a price, a policy or an announcement page with no feed, use Visualping. It does that well, and we don't try to.

If you follow people and publications and want to stop missing what they publish, that's us."

### Visualping facts used (2026-09-26)
- Monitors a whole page or a selected area; visual, text, or combined modes.
- Every alert includes an AI summary and an important/not-important flag; custom prompts define "important".
- Their AI rates 83% of detected changes as not important.
- Free: 5 pages, 150 checks/month, 60-minute minimum interval. Personal from $10/month: 10 pages, 1,000 checks. Business from $100/month (annual): 200 pages, 20,000 checks.

## Sources
- [Firecrawl](https://www.firecrawl.dev/)
- [What is Visualping? — Visualping Help](https://help.visualping.io/en/articles/4438913)
- [How Visualping AI filters noise and flags what matters](https://visualping.io/blog/analyzer-explained)
- [How Visualping Cuts False Positives](https://visualping.io/blog/how-visualping-cuts-false-positives)
- [Pricing — Visualping](https://visualping.io/pricing)
