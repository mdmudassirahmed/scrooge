# Agent model tiers

Subagents without a `model:` line inherit the parent session's model. If the lead runs on Opus or Fable, every research,
QA and documentation agent silently runs there too. Pin the model per role in `.claude/agents/<name>.md` frontmatter:

```markdown
---
name: backend-developer
description: Builds the API and database layer. Use for routes, migrations, RLS, webhooks.
tools: Read, Write, Edit, Glob, Grep, Bash
model: sonnet
---
```

Suggested starting tiers (adjust after a week of results):

| Tier | Model value | Typical roles |
|---|---|---|
| Routine, well-specified work | `sonnet` | project manager, QA, release, documentation, content, marketing, UX copy, most feature development |
| Judgement-heavy or security-sensitive | `opus` | architecture, AI/retrieval engineering, security review |
| Mechanical checks and monitoring | `haiku` | ops monitor, log triage, formatting |

Rules of thumb: measure before promoting a role to a costlier model; one Opus call costs about two Sonnet calls, one Fable
call about five. Workflow scripts: pass `model` in `agent()` options or the whole workflow inherits the parent.
