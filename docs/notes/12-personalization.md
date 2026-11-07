# Personalization and relevance (brainstorm, not decided)

Started 2026-09-26 after trying RSS.app and Feedly ([trial](case-studies/rssapp-feedly-trial.md)).

## The thesis
Competitors already cover "follow sites without RSS" and "summarize articles" ([11](11-landscape.md)). The more valuable thing: **a feed that learns what matters to its reader.** Feedly is not very customizable; RSS.app is very customizable but overwhelming. Aim: no configuration screens, but still personal.

Reliability is what makes this trustworthy: you can't personalize posts you never received, and a filtered feed that quietly broke looks the same as a filter doing its job.

## Terminology
The idea came up as "reinforcement learning". What's described is closer to **relevance feedback / preference learning**: the reader says what they like, and future ranking adjusts. It doesn't need a trained ML model to start; counting and weights go a long way.

## Three kinds of signal, cheapest and clearest first
| Signal | Example | How it's used |
|---|---|---|
| **Stated preferences** (natural language) | "Hide 'enzyme system' from Anthropic." "I care about funding and launches, not tutorials." | The model turns them into **editable rules** from a closed vocabulary: keyword mute, topic mute, post-type preference, scoped to one source or all. The user can see and undo them |
| **Explicit feedback** | 👍/👎, "more like this", "less like this" | Adjust weights on item features: source, post type, topics, companies/people mentioned |
| **Implicit feedback** | Which links get opened | Noisy, and tracking clicks in email has privacy costs. Later, opt-in |

## Relevance = content × what the reader expects (clarified 2026-09-26)
The same post can be right or wrong depending on where it comes from. "AI for Content Marketing" is off-expectation from Firecrawl's blog, but exactly right from a source about marketing tools, and may still hold something useful. So relevance depends on three things together:
- **The item's content** (what it's actually about),
- **The reader's general interests**,
- **The reader's expectation of this source** ("why I follow it").

Post type is one useful feature, not the rule. Decisions from this round:
1. Don't build around the post-type example; it was one illustration.
2. Feedback surface: discuss once the idea is agreed.
3. Mute scope (one source vs all): **it depends**; infer from context, ask when unclear.
4. Topic and keyword feeds: **not for now**.

## Rules: the model compiles, code applies
A stated preference is a prompt, but it's processed **once**, not per item. Same pattern as recipes ([00](00-project-brief.md)): the model writes a structured record, code runs it.

1. **Compile (model, once):** "hide enzyme posts from Anthropic" becomes a rule from a closed vocabulary:
   ```yaml
   - id: r12
     action: hide                       # hide | show | boost | demote
     scope: {source: anthropic-news}    # one source, or all
     match: {keywords: ["enzyme"]}      # keywords | topics | entities
     from_text: "hide enzyme posts from Anthropic"
   ```
2. **Confirm (user):** the model shows its interpretation: "Hide Anthropic posts mentioning 'enzyme'. Also hide biology research posts in general?" This is where "it depends" scope gets resolved.
3. **Apply (code, every item):** match against the item's title, summary, and the topics/entities added during enrichment. No model call. Hidden items carry the reason "rule r12".

Three kinds of rule, by how they're matched:
| Kind | Example | Matched by |
|---|---|---|
| Keyword | "enzyme" | Code: text match on title and summary |
| Topic / entity | "biology research", "OpenAI" | Code: labels assigned once per item during shared enrichment |
| Fuzzy intent | "nothing that's basically an ad" | Can't be a code rule. Becomes part of the **profile** and is applied by the judge (model, shortlist only) |

Keyword rules are literal: "enzyme" won't catch a post about protein design that never uses the word. Topic rules generalize better, but only as well as the enrichment labels. Open question: a fixed topic list, or open-ended tags?

## Source expectations (decided 2026-09-26)
When adding a source, an **optional** field: "What do you want from this source?" Also learned quietly from reactions over time.

## Post type: one feature among several
The Firecrawl example: about 3 of 25 posts are company news; the rest is content marketing. A **post-type** label on each new item gives a strong default before any personal feedback:

`announcement/launch · funding/business · research · release/changelog · customer story · how-to/tutorial · comparison/listicle · explainer · opinion · event`

- Classified once per **new item**, from title + summary, with a cheap model. Fits the core principle: the model runs per new item at curation, never per check.
- Default for company blogs could be "show company news, collapse the rest".

## Beyond summarizing
A summary restates the article. More valuable questions a digest can answer:
1. **Should I read this?** "Company news: raised a $75M Series B and launched Alexandria."
2. **What matters most this week**, across all sources.
3. **What connects:** "Three companies you follow shipped X this week."
4. **Why am I seeing this?** "Because you liked posts about Y" / "Funding news from a company you follow."

## Design principles and risks
- **Never drop silently.** Show "12 hidden" with the reason for each, and one-tap restore. Hidden-but-restored items are the best signal that a rule is wrong.
- **Explore a little.** Occasionally show a borderline item, so the feed doesn't narrow forever.
- **Cold start:** post-type defaults plus one onboarding question ("What do you want from these sources?").
- **Drift:** interests change; old feedback should fade.
- **Scope:** is a mute for this source only, or everywhere? Ask when unclear.
- **Explainability:** every hidden or promoted item can say why.
- **Evaluation:** share of shown items marked useful; share of hidden items restored.

## Where it touches the architecture
Curation grows from "dedupe, rank, summarize" into:

```
new items → rules (code) → classify: post type, topics (model, per new item)
          → score with the user's preferences (code) → budget per source (code)
          → "why it matters" notes (model, shortlist only) → digest
```

Preferences, rules and feedback are **per user**: they live with subscriptions, not with shared feeds ([00](00-project-brief.md) security baseline).

## Open questions
- Is the "company news vs content marketing" filter on by default?
- Where does feedback happen: buttons in email (signed per-item links), a web digest page, a chat bot (Telegram)?
- Do mutes default to one source or to all?
- Are topic and keyword feeds (RSS.app, Feedly) in scope, or strictly saved sources?
