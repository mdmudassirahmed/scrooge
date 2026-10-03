---
name: receipts
description: Measure where Claude Code token spend goes, from the session transcripts already on disk (context size per call, model mix, agent runs that inherited an expensive model, files read over and over, whether CLAUDE.md and project agents could load), then apply the structural fixes (a context cap with state re-injected after compaction, a read guard, tiered agents) and compare before and after. Use when the user asks why usage is high, how to cut Claude Code token cost without losing quality, or runs /receipts. Local only, never commits.
user-invocable: true
compatibility: Claude Code (agent skills SKILL.md format). Scripts need Python 3.8+ (standard library only) and run on Windows, macOS and Linux.
---

# Receipts

Evidence first, then fixes. Claude Code logs every session to `~/.claude/projects/<encoded-cwd>/*.jsonl` with the token counts of every call (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), the model, every tool call and every tool result. Subagent runs sit in subfolders. That is enough to say, with numbers, where the spend went and which fix would have changed it. Nothing is sent anywhere. Dollar figures are API list prices used only as a relative proxy for plan consumption.

## Commands

```
/receipts                          report for every project on this machine
/receipts --project <path|name>    one project (a cwd path, or its encoded folder name)
/receipts --since 7                only transcripts modified in the last 7 days
/receipts --json before.json       also save a snapshot for a later comparison
/receipts --compare before.json    before and after table against a saved snapshot
/receipts apply [--cap 300000]     global fixes in ~/.claude/settings.json (dry run, backup, then write)
/receipts scaffold <repo>          repo side: CLAUDE.md rules, post-compaction hook, agent model check
```

## What the report shows

1. Totals: tokens by kind and an API-dollar equivalent, split into lead sessions and subagents.
2. Context size per call in 100k buckets, and how many re-read tokens a cap at 200k, 300k, 400k or 500k would have avoided.
3. Model mix, and which transcripts each model dominated.
4. Agent dispatches by subagent type and the model given. "inherited" means no model was pinned, so the agent ran on the parent's model.
5. The folder each session started in, and whether a CLAUDE.md and a `.claude/agents` folder exist there. Project rules and agents load only from the session folder and its parents, so a session started one folder too high silently loses both.
6. Tool results by size, and files read whole three or more times.
7. The most expensive transcripts, with their first prompt.
8. Recommendations generated from the numbers above, each with its measured basis.

## How to run it (for Claude)

1. Run `python "<skill-dir>/scripts/audit.py" [args]` (`<skill-dir>` is the folder containing this file). Show the user the sections that matter: totals, the context histogram with the cap table, model mix, agent dispatch, repeated reads, and the session-folder check.
2. Turn section 8 into a short ranked list with the measured number behind each item. Say which items are documented Claude Code mechanisms (the auto-compact window, hooks, agent `model:` frontmatter) and which are estimates. Give ranges from the data, never promises.
3. For `apply`: run `python "<skill-dir>/scripts/apply.py" --dry-run` first and show exactly what would change. Get the user's go, then run it without `--dry-run`. It edits `~/.claude/settings.json` (`cleanupPeriodDays`, `env.CLAUDE_CODE_AUTO_COMPACT_WINDOW`, optional `autoMemoryDirectory`, a PreToolUse read-guard hook), writes a timestamped backup, installs `~/.claude/hooks/read_guard.py` and prints before and after. New sessions pick it up; running sessions keep their startup values.
4. For `scaffold <repo>`: `python "<skill-dir>/scripts/apply.py" scaffold <repo>` writes `.claude/settings.json` (a SessionStart hook with matcher `compact`), `tools/hooks/post_compact_context.py`, appends the token-discipline section to CLAUDE.md if it is missing, and lists agents in `.claude/agents` without a `model:` line (see `templates/agent-model-tiers.md` for suggested tiers). Tell the user the files are uncommitted.
5. Before and after: save `--json before.json` on day one, work normally for a week, then run `--since 7 --compare before.json`. Report the table as it is.

## What the fixes do, and why they are safe

- The context cap only makes compaction happen earlier. The post-compaction hook prints exact state from disk (task tracker, newest hand-off section, last commit, git status) into the fresh context, so facts come from files rather than from the summary. Keep requirements in a spec file and name it in the hand-off; the CLAUDE.md section tells Claude to re-read it after compaction.
- The read guard denies a whole-file `Read` of a text file above 40 KB (`READ_GUARD_MAX_BYTES` changes the limit) and asks for `offset` and `limit` or Grep. Images, PDFs and notebooks are exempt.
- Tiered agents: a subagent without `model:` runs on the parent's model. Pin sonnet for routine roles, opus for judgement-heavy ones, haiku for mechanical checks, and pass `model` in Workflow `agent()` calls too.

## What it will not do

No git commits, no deletions, no network calls, and no edits outside `~/.claude` and the repo the user names. Worktree clean-up and model choices are reported, never performed.
