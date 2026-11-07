# Why not just use Claude routines or ChatGPT tasks?

The starting question of this project ([00](00-project-brief.md)) was whether a scheduled AI run could track blogs for us. Short answer: **it can, but it's the wrong place for the whole system.** A scheduled model run puts a model in the per-check loop, which is exactly what the architecture ([04](04-architecture.md)) avoids. It can still be a reasonable *runner* for the steps that genuinely need a model.

Limits below were checked on 2026-09-26 against the vendors' docs. They change; re-check before relying on them.

## What each one is

| | Claude Code routines | ChatGPT scheduled tasks |
|---|---|---|
| What runs | A Claude Code session in Anthropic's cloud, from a saved prompt, repo(s) and connectors | A saved prompt run by ChatGPT on a schedule |
| Minimum interval | 1 hour (more frequent schedules are rejected) | 1 hour; Free users at most once a day |
| Volume cap | Runs per day: **Pro 5, Max 15, Team/Enterprise 25**, shared by all routines; extra usage beyond that | Active tasks: **Free/Go 3, Plus 5, Business/Edu 10, Pro/Enterprise 15** |
| State between runs | None in the session. Repos are cloned fresh from the default branch each run; Claude's changes go to `claude/`-prefixed branches | Not described as having files or a repository |
| Can run our code | Yes, inside the cloned repo | Not a code-execution environment we control |
| Network | Set by the cloud environment's network access setting | ChatGPT's own tools |
| Output | Commits/branches, connectors (Slack, email, etc.) | Push notification or email when done |
| Other | Also triggerable by API (30 fires/hour per routine, 100/hour per account) or GitHub events | Unattended tasks may pause after a period of inactivity |

## Why neither works as the whole system

Checked against what the architecture needs:

| Requirement | Why a scheduled model run struggles |
|---|---|
| **No model in the per-check loop** | Every run *is* a model session. Checking 50 sources by having the model fetch and read them costs tokens on every check, including all the checks that find nothing new — for slow blogs, that's nearly all of them |
| **Per-source schedules** | One schedule per routine/task, and caps of 5-25 means you can't give each source its own cadence. Everything collapses into one "check all" run |
| **Memory of what's been seen** | Without a seen-URL set, the model re-reports old posts or guesses what's new from dates — and [Anthropic](case-studies/anthropic-news.md) and [OpenAI](case-studies/openai-news.md) showed dates are unreliable (sitemap `lastmod` is not publish time; feeds aren't in date order) |
| **Deterministic diffing** | "What's new since last time" is a set difference. A model doing it by reading pages can miss items or invent them, and it's different on every run |
| **Health checks and self-healing** | Telling "no new posts" from "broken source" needs history per source (item counts, known posts, typical gaps). A stateless run has none |
| **Validation of recipes** | The architecture only adopts a recipe that reproduces known posts. That needs stored fixtures and code to run them |
| **Access problems** | Unchanged. A scheduled run fetches pages the same way: 403s, JavaScript-only pages and bot protection still block it ([OpenAI](case-studies/openai-news.md)) |
| **Cost predictability** | Usage grows with sources × checks, instead of with new posts |

ChatGPT's own example for tasks is *"give me a briefing on AI news each afternoon"*. That's a **search-driven briefing** — whatever the model finds that day — not **tracking specific saved sources** reliably. It's a different product from the one we're building.

## Where a routine *could* fit

Not as the checker, but as the runner for the model steps:

```
cron / scheduler (no model)          routine, once a day (model)
───────────────────────────          ───────────────────────────
node check.mjs every few hours  →    read new items from state
  diff, health checks, state         curate: dedupe, rank, summarize
                                     send the digest via a connector
```

Or, fully inside a routine: the routine's prompt says "run `node check.mjs`, then curate what it found". The checks cost no tokens (it's our script), and the model only does curation. Frictions to plan for:

- **State must survive a fresh clone.** The seen set and fixtures have to be committed back, and changes land on `claude/` branches by default, so state needs its own branch or an external store.
- **One run per day fits the caps comfortably** (it's one of your 5 on Pro); hourly checking does not.
- **Self-healing inside a routine** is plausible (it's a model session with the repo), but the output should still be a recipe diff that passes validation, not an ad-hoc fix.

## Conclusion
- A scheduled AI run is a fine **scheduler for model work** (curation, digest, occasional repair).
- It's a poor **engine for monitoring**: stateless, capped, non-deterministic, and it spends tokens on every empty check.
- The monitoring engine should be plain code with files on disk; whether it's triggered by cron, a routine, or a server is a deployment choice, not an architectural one.

## Sources
- [Automate work with routines — Claude Code Docs](https://code.claude.com/docs/en/routines)
- [Configure cloud environments — Claude Code Docs](https://code.claude.com/docs/en/cloud-environments)
- [Run prompts on a schedule — Claude Code Docs](https://code.claude.com/docs/en/scheduled-tasks)
- [Trigger a routine through the API — Claude Platform Docs](https://platform.claude.com/docs/en/api/claude-code/routines-fire)
- [Scheduled tasks in ChatGPT — OpenAI Help Center](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)
