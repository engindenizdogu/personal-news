# Finding a company's ATS board token

The "board token" is just the company's slug on the ATS host. For Greenhouse it's the `X` in
`https://job-boards.greenhouse.io/X`, and the API is `https://boards-api.greenhouse.io/v1/boards/X/jobs`.

Same idea per vendor:
| Vendor | Public board URL | API |
|---|---|---|
| Greenhouse | `job-boards.greenhouse.io/<slug>` (also `.eu`, older `boards.greenhouse.io`) | `boards-api.greenhouse.io/v1/boards/<slug>/jobs` |
| Lever | `jobs.lever.co/<slug>` | `api.lever.co/v0/postings/<slug>?mode=json` |
| Ashby | `jobs.ashbyhq.com/<slug>` | `api.ashbyhq.com/posting-api/job-board/<slug>` |
| Workday | `<tenant>.myworkdayjobs.com/<site>` | CXS endpoint (POST, paginated) |

## Four ways to get it, cheapest first

### 1. Read it off the careers page
Company career pages usually either redirect to, link to, or embed the ATS board. Grep the HTML for the ATS host. Helper: `docs/scripts/find-board.sh` (below).

Works when the page is server-rendered and not blocked. In testing: `ramp.com/careers` → `ashby: ramp`. It found nothing for `anthropic.com/careers` (JS-rendered) and `openai.com/careers` (403), which is the usual failure mode.

### 2. Look at a job posting's own URL
Click any job, then read the address bar. Embedded boards leak the token in several ways:
- `job-boards.greenhouse.io/<slug>/jobs/123`
- `boards.greenhouse.io/embed/job_board?for=<slug>`
- an apply link containing `gh_jid=` (Greenhouse job id) — the slug is elsewhere in the same URL or in the iframe `src`
- Workday: the tenant is the subdomain of `*.myworkdayjobs.com`

### 3. Guess the slug and probe the API
The slug is usually the company name, lowercased with punctuation stripped. Verified live:

| Guess | Greenhouse result |
|---|---|
| `anthropic` | 200 — 596 jobs |
| `figma` | 200 — 154 jobs |
| `stripe` | 200 — 647 jobs |
| `notion` | 404 |
| `ramp` | 404 (it's on Ashby: `ramp`) |

A 404 means "not this vendor, or not this spelling", so try the next vendor. career-ops does exactly this in `discover-ats.mjs`, probing vendors in a fixed cost order:
```
gh, ashby, lever, workable, smartrecruiters, recruitee, bamboohr, breezy, pinpoint, rippling, join
```
Its rule for success is stricter than a 200: a company **"resolves" when a vendor's board exists AND currently lists ≥1 job.** Companies that don't resolve (JS-rendered portals, non-standard slugs, Workday without a hint) are **flagged for manual follow-up rather than silently dropped**.

### 4. Open the network tab
Load the careers page in a browser, filter requests by `greenhouse`/`ashby`/`lever`/`workday`. The board request appears with the slug in it. Same technique as OpenAI's `/backend/articles/` in [OpenAI](openai-news.md).

## Pitfalls
- **Slug ≠ company name**: `talkdesk2`, not `talkdesk` (a real one-character miss noted in career-ops's `audit-portals.mjs`).
- **Right vendor, wrong entity**: a subsidiary's board can resolve to the *parent's* board and still return 200 with postings. Check that the jobs actually belong to the company.
- **Regional hosts**: `job-boards.eu.greenhouse.io`, `jobs.eu.lever.co`.
- **Multiple boards**: some companies run separate boards per brand or region.

## Helper script
`docs/scripts/find-board.sh <careers-url>` — prints any Greenhouse/Lever/Ashby/Workday slug found in a careers page's HTML.
