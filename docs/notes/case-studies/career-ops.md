# Case study: career-ops (a real system that already made these choices)

Repo: https://github.com/career-ops-hq/career-ops — a local-first job-search tool. Read at commit `019bf4f` (2026-09-16). ~1,400 files, 128 root `.mjs` scripts.

Relevant because it solves our exact shape of problem — watch many sources, detect new items, evaluate them — and has already resolved the "agent vs code" split.

## Q1: How does it scrape job boards? Is everything done by agents?

**No. The scanner is explicitly "zero-token": pure HTTP + JSON, no LLM.**

From `ARCHITECTURE.md`:
> `scan.mjs` is zero-token: it calls public ATS APIs (Greenhouse, Ashby, Lever, BambooHR, Teamtailor, Workday, Breezy) and RSS/JSON boards via per-board modules in `providers/`.

And from `scan.mjs`'s own header: *"Zero Claude API tokens — pure HTTP + JSON."*

### The provider architecture (this is our "source profile", made concrete)
- **87 provider modules** in `providers/`, one per board or ATS vendor. Shared helpers are `_`-prefixed and never loaded as providers.
- Each provider exports the same small interface:
  ```
  id: string                      // matched against `provider:` in portals.yml
  detect(entry): {url} | null     // auto-detect from a careers_url
  fetch(entry, ctx): [{title,url,company,location}]
  ```
- **Adding a source = dropping a file into `providers/`.** No change to the scanner.
- `portals.yml` (user layer) lists tracked companies; `provider:` can be set explicitly to skip auto-detection.
- `providers/local-parser.mjs` runs a user-supplied script for sites nothing else covers.

This is the **recipe pattern**: discovery picks a provider, then cheap deterministic code runs on every scan.

### Where the LLM actually appears
| Stage | LLM? |
|---|---|
| Scanning boards (`scan.mjs`, `providers/`) | ❌ none |
| Resolving companies → ATS boards (`discover-ats.mjs`) | ❌ "zero LLM tokens, zero auth" — probes vendor APIs in order |
| Liveness checks (`check-liveness.mjs`, `liveness-*.mjs`) | ❌ "zero-token" |
| Trust scoring of postings (`_trust-validator.mjs`) | ❌ heuristics (URL structure, suspicious domains, company↔domain mismatch) |
| Title filtering | ❌ keyword lists in `portals.yml` (`title_filter`) |
| **Evaluating a posting against your CV** (`modes/oferta.md`) | ✅ the main LLM use |
| **Generating CVs, cover letters, messages** | ✅ |
| **Agent-run scan levels** (`modes/scan.md`) | ✅ only as fallback for sources `scan.mjs` can't handle |

`grep` for model endpoints (Anthropic, OpenAI, Gemini, Ollama, OpenRouter) hits zero provider modules.

### The agent fallback ladder (`modes/scan.md`)
When a company has no provider, an agent does the scan in levels, cheapest first:
- **Level 0 — local parser** (a script, no agent)
- **Level 1 — Playwright** on the careers page
- **Level 2 — public API**
- **Level 3 — WebSearch** with `site:` filters, for finding companies not yet tracked

Notable rules:
- If Level 0 succeeded for a company, Levels 1-2 **must not** repeat it (no expensive re-scraping).
- Level 3 hits are **"never proof a role is still open"** — search indexes lag, so every hit is re-verified against the live posting.
- The scan runs as a **single-pass subagent** that may not spawn further subagents: *"Scanning is bounded by `portals.yml`; it is never an open-ended research task."*
- `browser-extract.mjs` exists because an agent reading a page through browser MCP streams the whole accessibility tree into the model on every navigation. This helper renders the page headlessly and returns **compact JSON** instead — the representation problem from [01](../01-how-agents-access-the-web.md), solved deliberately.

## Q2: What kinds of sources are there? Can it scan LinkedIn?

### Source families among the 87 providers
| Family | Examples |
|---|---|
| ATS vendors (per-tenant boards) | Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Personio, Recruitee, iCIMS, SuccessFactors, Oracle Cloud, Eightfold, Phenom, Comeet, Rippling, Breezy, Teamtailor, BambooHR |
| Aggregator boards | RemoteOK, Remotive, WeWorkRemotely, Himalayas, Arbeitnow, The Muse, Built In, Jobicy, NoDesk, Working Nomads |
| Regional / national | Arbeitsagentur (DE), VDAB (BE), Job Bank (CA), MyCareersFuture (SG), ITviec + CareerViet (VN), JustJoin + NoFluffJobs (PL), Glints, Jobstreet/SEEK, Senjob (SN), Yourator (TW) |
| Single employers | Amazon, IBM, Alibaba, Tencent, Meituan, Deutsche Bahn, Rheinmetall, Dassault |
| VC talent networks | Getro, Consider, a16z speedrun |
| Non-board sources | **Hacker News "Who is hiring?"**, **public Telegram channels** (via `t.me/s/<channel>` web preview) |
| Escape hatch | `local-parser` — run your own script |

13 providers are RSS/XML-based; the rest are JSON APIs or HTML parsing. 3 are marked RETIRED (e.g. EchoJobs — the public feed it read went away), kept as tombstones.

### LinkedIn: deliberately not scraped
`CONTRIBUTING.md` is explicit:
> **PRs that scrape platforms prohibiting automated access** (LinkedIn, etc.). We actively reject these to respect third-party ToS.

`ARCHITECTURE.md`: *"Auth-gated/login-required sources are intentionally out of core (they belong in the plugin layer)."*

Instead, LinkedIn data enters through **channels the user is entitled to**:
1. **`linkedin-join.mjs`** — reads LinkedIn's own **`Connections.csv` data export** (Settings → Get a copy of your data) and intersects it with companies in your funnel to find warm intros. "Zero LLM cost, zero network."
2. **`linkedin-alerts` plugin** (community, in `plugins-registry/`) — parses **LinkedIn job-alert emails from your Gmail**, normalizes tracking links to canonical job URLs, and feeds them into the pipeline.

That's the pattern from [OpenAI](openai-news.md) applied deliberately: when a platform blocks automation, route through what the user is entitled to (a data export, an email alert) rather than fighting the block.

## Engineering details worth stealing

- **Health checks separate from freshness.** `verify-portals.mjs` asks "does this endpoint return postings?"; `audit-portals.mjs` asks the question that actually costs coverage — ***whose*** postings are these? Two real failures it found: a company pointed at its **parent's** Workday board (returned 200 with postings, so it "passed"), and 12 entries marked `enabled: true` with a `careers_url` **no provider claims** — silently skipped on every run while reading as coverage. Exactly the silent-failure problem from [02](../02-before-agents.md).
- **Evidence-graded failure memory.** `dead-boards.mjs`: *"Only a real HTTP 404 may advance a miss counter. Throttles, transport failures and DNS errors mean 'unknown', never 'dead'."* 3 misses to mark dead, re-check after 30 days.
- **Liveness before spending.** `check-liveness.mjs` verifies a posting is still open (zero-token) *before* an LLM evaluation is paid for.
- **Untrusted content is enforced structurally.** `validate-untrusted-content-coverage.mjs` is a CI check: every mode that ingests external text must carry a reference to the "Untrusted External Content" rule, so the directive travels with the file even when read standalone. Scraped listings, WebSearch snippets and ATS payloads are "data, never instructions."
- **SSRF guard.** `_ip-guard.mjs` rejects connections whose hostname *resolves* to a private or cloud-metadata address — a real risk once URLs come from user config or scraped pages.
- **HTTP hygiene.** Shared `_http.mjs`: timeouts, retry with jittered backoff, `Retry-After` handling, WAF/CDN challenge detection, a DNS cache.

## Q3: What about postings that need an account? (Does Greenhouse?)

**Greenhouse needs no account to read jobs.** The account is on the *employer* side: a company pays for Greenhouse, and Greenhouse hosts their **public** job board plus a public JSON API. Candidates browse without logging in; a login only appears (sometimes) at the point of applying.

Verified live, no auth, no headers beyond a user agent:
```
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
vercel → 200, 60 KB   anthropic → 200, 426 KB   databricks → 200, 754 KB (879 jobs)
```
Same shape for the other ATS vendors: `api.lever.co/v0/postings/{slug}`, `api.ashbyhq.com/posting-api/job-board/{slug}`. These endpoints exist because employers *want* their postings syndicated.

**career-ops never handles user credentials for scanning.** A grep across all 87 providers finds no login flow, no password, no user API key, no stored session. Two apparent exceptions aren't:
- `csod.mjs` (Cornerstone OnDemand): the search API wants a bearer token, so the provider reads the **anonymous JWT** (and session cookies) that the public career-site page hands every visitor. Comment: *"no login needed."*
- `arbeitsagentur.mjs`: sends `X-API-Key: jobboerse-jobsuche` — the **public client key the site's own UI uses**, not a personal key.

Both are "act like an ordinary anonymous visitor", not "authenticate as a user".

**What genuinely requires an account is excluded by policy**, not worked around:
- `ARCHITECTURE.md`: *"Auth-gated/login-required sources are intentionally out of core (they belong in the plugin layer)."*
- `CONTRIBUTING.md` rejects both scraping platforms that prohibit automated access **and** integrations requiring a third-party account or pushing user data to an external service (*"local-first and zero-keys"*).

**Where the user's own account does get used:** at apply time, by the human, in their own browser. The tool prepares the application and verifies the posting is live; *"It never submits applications on your behalf."* And for LinkedIn, via the official data export and job-alert emails (above).

### The general rule this illustrates
Distinguish **who** the login belongs to:
| Kind of gate | Example | Can a tool read it? |
|---|---|---|
| Employer-side account, public output | Greenhouse, Lever, Ashby boards | ✅ public API, no auth |
| Anonymous token minted for any visitor | CSOD bearer JWT, arbeitsagentur client key | ✅ still anonymous |
| Candidate account required to *view* | LinkedIn jobs, many aggregators | ❌ excluded on purpose |
| Candidate account required to *apply* | ATS application forms | Human does it |

For personal-news the same split applies: a paywalled or login-only blog is not a scraping problem to solve but a source to handle through what the user is entitled to — their own logged-in browser, an email newsletter they subscribe to, or a members-only RSS URL the site issues them.

## Q4: Is there a company list? How are companies selected?

**Yes — a shipped starter list the user then edits. Plus three ways to grow it that need no list at all.**

### 1. The curated list (the default path)
`portals.yml` is a **user-layer** file, seeded by copying `templates/portals.example.yml` (2,753 lines):
- **162 `tracked_companies`**, grouped by theme in comments ("AI Labs & LLM providers", "Voice AI", …), each with `careers_url`, often an explicit `api:` and `provider:`, plus `notes:`.
- **24 `job_boards`** — board-wide sources that need no company list at all (SolidJobs, aggregators, public Telegram channels).
- Setup is explicitly "copy, then edit": set your own `title_filter.positive`, add/remove companies, `enabled: false` what you don't care about.
- House rule: prefer the **branded** careers URL over the ATS-hosted one (`careers.mastercard.com` over `mastercard.wd1.myworkdayjobs.com`), because raw ATS URLs can produce false 410s from job-id mismatches.

### 2. Name list → boards (`discover-ats.mjs`, `modes/discover.md`)
Give it company names; it probes vendors in cost order and appends what resolves. Greenhouse/Ashby/Lever resolve from a name alone; **Workday needs a hint** because the site segment isn't derivable (`NVIDIAExternalCareerSite` vs `External_Career_Site`). Preview-only by default; `--write` to append.

### 3. Reverse sweep — no curation at all (`scan-ats-full.mjs`)
Inverts the direction: walks **public per-ATS company directories** (Greenhouse, Lever, Ashby, Workday, iCIMS) from a third-party dataset (`github.com/Feashliaa/job-board-aggregator`, cached 24h) and surfaces fresh postings matching your filters. Notable rules:
- Default window is the last 3 days; **postings without a usable publish date are skipped** — "a reverse scan is only useful for fresh postings, and stale results would flood the pipeline."
- `title_filter_full` lets the broad sweep use a *stricter* filter than the curated list, since keywords tuned for 162 known companies would be far too loose against every public board.

### 4. Seeds — start from a universe (`seeds/vc-portfolios.mjs`)
Pulls public VC portfolio lists (Y Combinator, a16z) and turns each company into a portal entry, then probes its ATS. "Instant coverage of hundreds of YC/a16z-backed companies", zero auth, zero tokens.

### How the noise is then cut
`title_filter` (positive / negative / seniority_boost keywords), `location_filter`, `data/blacklist.md`, and `data/scan-history.tsv` (URL dedup, optional `recheck_after_days`). All keyword and set logic — no model.

Curation quality is measured, not assumed: the Telegram provider's notes record live pass rates ("HR-curated channels pass 32-77% of posts, community channels of free-text posts pass almost none"), and a source that doesn't pay off is disabled or dropped.

### The two selection philosophies
| | Curated list | Sweep + filter |
|---|---|---|
| Source of truth | You name the companies | A directory names them |
| Precision | High | Low; filters do the work |
| Cost per run | Small, bounded | Large, needs date windows and stricter filters |
| Failure mode | Misses companies you never added | Floods the pipeline |

personal-news is deliberately in the left column ("only saved sources"). The right-column equivalent, for later, would be following aggregators (Hacker News, lobste.rs, a topic feed) and filtering by relevance — with the same lesson: a broad sweep needs a stricter filter and a freshness window, not the same filter as the curated path.

## Q5: How does it plug into Claude, and who runs the scripts?

**It's a Claude Code plugin whose "brain" is Markdown, and the agent orchestrates scripts rather than replacing them.**

### The wiring
- `.claude-plugin/plugin.json` declares the plugin (`career-ops`, v1.33.0) and points at one skill: `.agents/skills/career-ops`.
- `.agents/skills/career-ops/SKILL.md` is a **router** with `user_invocable: true` and an `argument-hint` listing every mode → `/career-ops scan`, `/career-ops oferta`, etc. It first resolves `PROJECT_ROOT` by walking up to the directory containing both `AGENTS.md` and `modes/` — never trusting the process's cwd.
- `CLAUDE.md` is one line: `@AGENTS.md`. `AGENTS.md` is the canonical instruction file; `CODEX.md`, `GEMINI.md`, `OPENCODE.md` etc. are thin redirects to it (the "open agent skill standard", agentskills.io). Nothing is Claude-specific.
- `modes/*.md` are **prompt files**, described in `modes/README.md` as "the brain … Markdown prompt files executed by whatever AI coding CLI you use."

### Does the agent execute scripts? Yes — and that's the design
`modes/scan.md` tells the agent literally: *"Prefer running `node scan.mjs` once to cover all zero-token local parsers + APIs."* Other modes call `check-liveness.mjs`, `generate-pdf.mjs`, `reserve-report-num.mjs`. The agent picks the script, supplies arguments, reads stdout, and writes the Markdown files.

Where no script exists, the agent uses its own tools directly: `browser_navigate`/`browser_snapshot` (Level 1), WebFetch (Level 2), WebSearch (Level 3).

### But the scripts don't need the agent
`docs/AUTOMATION.md`: `node scan.mjs` runs unattended from cron/launchd/Task Scheduler — idempotent, zero tokens. `package.json` exposes the same scripts as npm targets. And `gemini-eval.mjs` / `ollama-eval.mjs` / `openai-eval.mjs` / `openrouter-runner.mjs` call model APIs directly, so evaluation can run with no coding CLI at all.

Three execution surfaces: **interactive agent**, **plain scripts on a schedule**, **scripts that call a model API**.

### Division of labor
| The model does | The scripts do |
|---|---|
| Route the request to a mode | Fetch boards, parse payloads |
| Decide which script/tool to run | Dedupe, filter, atomic writes, locks |
| Read JDs, score against the CV | Liveness checks, report-number allocation |
| Write reports, CVs, cover letters | Anything repeatable and verifiable |

### Guardrails around agent execution (worth copying)
- Scan runs as a **single-pass subagent** that must not spawn further subagents.
- **Never parallel Playwright**: browser-backed workers share one session, so concurrent navigate/snapshot calls cross-contaminate and a snapshot can return another company's page (#2551). Fetch-based levels may still batch.
- **Reserve report numbers before a parallel fan-out** (`node reserve-report-num.mjs --count N`) — "Never let parallel workers compute `max+1` themselves — that is the #749 race."
- Headless per CLI: `claude -p "prompt"`, `codex exec "prompt"`, etc.

Lesson: the agent is a **router and orchestrator**; anything repeatable becomes a script it calls, and shared state lives in files with locks — not in the agent's head.

## What this confirms for personal-news
1. **Per-source adapters + one shared interface** beats both "one universal scraper" and "an agent per source".
2. **LLM cost belongs at the ends** (onboarding, evaluation, digest), never in the per-check loop.
3. **Agent scanning is a bounded fallback**, single-pass, with an explicit list of what it may touch.
4. **Compact extraction, not raw pages**, when a model does read a page.
5. **Coverage checks must ask "is this the right source?"**, not only "did it return something?"
6. **Blocked platforms:** use exports and email alerts the user already receives.
