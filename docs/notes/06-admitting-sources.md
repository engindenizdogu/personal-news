# Admitting sources: what if the URL isn't a publication?

The case: a user pastes something that isn't a blog or newsletter, like a Google Calendar link. If it returns nothing, validation fails and we're done. The harder case is when it **returns content**.

## The gap in the current design
Validation ([04](04-architecture.md)) asks: *does this recipe faithfully track this URL?* (Does it contain the saved URL, and can it reproduce known posts?)

It never asks: *should we track this URL at all?*

A calendar feed passes the first question easily. It's structured, it has items with dates and links, and it's self-consistent. The fallback layers make it worse, because they're the permissive ones: "extract links from the HTML" or "model, find something" will produce a recipe from almost any page.

So **admission** has to be its own check. Fidelity and appropriateness are different questions.

## What "returns content" can mean
| Kind | Example | Risk if admitted |
|---|---|---|
| **Private by URL** | Google Calendar secret iCal address, Google Docs/Drive share link, Dropbox link, signed S3 URL (`X-Amz-Signature`), URLs with `token=`/`key=`/`sig=` | The URL *is* the credential. Storing it, fetching it on a schedule and passing the content to a model leaks private data |
| **Side effects on GET** | Unsubscribe links, email confirmation, magic login, password reset, "one-click" actions | Fetching it *does something*: unsubscribes the user, confirms an account, burns a login link |
| **Structured, but not posts** | Public calendar (`.ics`), product page with prices, job board, stock or weather page | Items get reported as "new articles"; events are future-dated, prices churn |
| **Churning pages** | Homepages with random or rotating items, "trending", search results | Every check looks "new", so the digest fills with noise |
| **Huge or unbounded** | Video, large PDF, archive, streaming endpoint | Bandwidth, memory, timeouts |
| **Not public / not ours to reach** | `localhost`, `192.168.x.x`, `169.254.169.254` (cloud metadata), `file://` | SSRF: the fetcher becomes a way to reach internal systems. career-ops's `_ip-guard.mjs` exists for exactly this ([career-ops](case-studies/career-ops.md)) |
| **Hostile content** | Any page | Prompt injection when a model reads it |

## Admission gate: layers in order
Ordered by cost, and also by privacy: the checks that protect private data must happen **before the first fetch and before any model sees anything**.

### 1. URL only, before fetching (code)
- Scheme must be `https` or `http`. No credentials in the URL (`user:pass@`).
- Resolve the host and require a public IP (no private, loopback, link-local or metadata ranges). Re-check after every redirect.
- **Secret-looking URLs:** query parameters like `token`, `key`, `sig`, `signature`, `X-Amz-*`, `auth`; path segments like `private-…`; known share hosts (`calendar.google.com`, `docs.google.com`, `drive.google.com`, `dropbox.com`). Don't fetch. Ask the user.
- **Action-looking URLs:** paths or params containing `unsubscribe`, `confirm`, `verify`, `login`, `reset`, `activate`. Don't fetch. Reject with the reason.
- Shorteners: resolve with a HEAD request (redirects only, no body), then run this layer again on the final URL.

### 2. Response headers (code)
- `Content-Type` allowlist: `text/html`, `application/rss+xml`, `application/atom+xml`, `application/xml`/`text/xml`, `application/json`.
- `text/calendar` → "this is a calendar, not a publication."
- Size cap and timeout; stream and abort past the cap. Limit redirects.

### 3. Shape of the items (code)
What posts look like, and what calendars and product pages don't:
- Each item links to its own distinct page, on the source's site.
- Items have titles.
- **Dates are mostly in the past.** Posts are published; events are scheduled. A majority of future dates → not a publication.
- Items look like prose, not prices, times or SKUs.

### 4. Probation, over time (code)
The first few checks are recorded but not delivered:
- **Growth, not churn:** a publication adds items and keeps old ones. If most items are replaced between checks without the set growing, it's a rotating page.
- Rate sanity: 40 "new posts" per hour from one source means something else is going on.

### 5. Classification when rules can't decide (model)
Only after layers 1-2 pass, so private or side-effecting URLs never reach it. Given a *summary* of the evidence (host, content type, item sample, date distribution), answer from a **closed set**:

`blog · newsletter · changelog/releases · video channel · podcast · forum · calendar · document · product/listing page · other`

This is where knowledge helps: a model recognizes "this is a Google Calendar embed" or "this is a GitHub releases page" without special code for each.

### 6. The user decides the edge cases
Default is **reject with a reason**, not guess:
> This looks like a calendar (events are scheduled in the future), not a publication. Don't follow / Follow its events anyway

## Supported kinds are a closed set
Some "unintended" inputs are legitimate wishes: a public meetup calendar, GitHub releases, a YouTube channel. The answer isn't to accept anything that parses. It's a **small, explicit list of source kinds**, each with its own meaning of "a new item":

| Kind | A new item is | Notes |
|---|---|---|
| Blog / newsletter | A post | The core case |
| Releases / changelog | A version | GitHub has `.atom` feeds for releases |
| Video channel / podcast | An episode | Usually have feeds |
| Calendar (opt-in, later) | A newly *announced* event | Needs different logic: future dates are expected |

Anything outside the list is rejected with a reason. Same principle as the recipe vocabulary: the model can choose among options; it can't invent new ones.

## Decisions (2026-09-26)
- **Scope is general**, not blogs only: any source whose items are publications (posts, videos, releases, episodes), as long as the risky cases stay out.
- **The response type is a primary signal** for admission.
- **No passwords or tokens in URLs, for now.** Possibly allowed later (e.g. a shared team Dropbox folder), as an explicit opt-in.

## Checked: YouTube needs no special code
Tested 2026-09-26 with plain `curl`:
- `youtube.com/@anthropic-ai` and `youtube.com/@GoogleDevelopers` both return 200 with a standard `<link rel="alternate" type="application/rss+xml">` tag pointing to `youtube.com/feeds/videos.xml?channel_id=…`.
- The feed is Atom (`text/xml`), with the **15 most recent videos** and publish dates.
- A wrong handle (`@AnthropicAI`) returned 404, so admission rejects it without help.

So the generic probe ladder handles YouTube. What was filed under "knowledge, not evidence" turned out to be evidence. One consequence: the feed only holds the latest 15, so a channel posting more than 15 videos between checks would lose some. The check interval has to stay shorter than that window.

## Checked: private pages don't return "nothing"
Plain `GET`s to signed-in-only pages, following redirects:

| Requested | Result |
|---|---|
| `mail.google.com/mail/` | 200 after 3 redirects, 1.2 MB, ends at `accounts.google.com/v3/signin/…` |
| `github.com/settings/profile` | 200 after 1 redirect, 47 KB, ends at `github.com/login?return_to=…` |
| `linkedin.com/feed/` | 200 after 1 redirect, 502 KB, ends at `linkedin.com/uas/login?…` |

They all "succeed" with a large login page, which the permissive fallbacks could turn into a recipe. Detection (code, layer 2):
- The final URL moved to a sign-in host or path (`accounts.*`, `/login`, `/signin`, `/uas/login`).
- A return-to parameter appears (`return_to`, `continue`, `session_redirect`, `next`).
- The page contains a password field.

Result: reject as "requires sign-in".

The bigger risk is the opposite case: a fetcher that carries the user's cookies, for example a browser fallback that reuses the user's real profile. Then the same `GET` returns the private content. **All fetching uses a clean, cookieless session.** Any exception is a deliberate, per-source choice.

## If tokens are allowed later
Treat the tokenized URL as a **secret**, not as config:
- Store it in a secrets store, not in `sources.yml`. The recipe refers to it by name.
- Redact it in logs, errors and digests.
- Never send the URL itself to a model. Content from it only reaches the model if the user opted in for that source.
- Per-source opt-in, shown clearly in the source list.

## Worked example: Google Calendar
| What was pasted | Layer that stops it | Outcome |
|---|---|---|
| Secret iCal address (`…/private-…/basic.ics`) | 1: secret-looking URL, known share host | Not fetched. "This link gives access to a private calendar. Don't paste it here." |
| Public iCal address (`…/public/basic.ics`) | 2: `Content-Type: text/calendar` | "This is a calendar, not a publication." |
| Public embed page (`…/calendar/embed?src=…`) | 3: no post-shaped items; 5: model says "calendar" | Rejected with the reason |
| Link to one event | 3: a single item, future-dated | Rejected |

Nothing here needs special code for Google Calendar except the share-host list in layer 1. The rest falls out of general rules about what a publication looks like.
