## Token discipline (installed by /receipts)
- Start every session from this repo folder, never from a parent or home directory, so this file and `.claude/agents/` load.
  Dispatch work only to the named agents in `.claude/agents/` (each has a `model:` line), never to `general-purpose`;
  in Workflow scripts pass `model:` explicitly in every `agent()` call.
- Before starting a task, write its full requirements to a spec file (for example `docs/specs/<TASK-ID>.md`) and name that
  file in the hand-off document. After any compaction, re-read that spec and the newest hand-off section before continuing;
  never assume a step was done without evidence.
- One bounded task per subagent. Start a fresh lead session per work window. Use `/compact <what to keep>` at milestones, not mid-task.
- Files over 40 KB: read with `offset`/`limit` or Grep, never whole (a hook enforces this). Long command output: redirect to a
  log file, then show the summary line, the failure count, the failing lines and the last 30 lines, never the raw log.
- Hand-back reports of 300 words or fewer, in this order: What changed · Files · Tests (pass/fail counts) · Commit SHA ·
  Blockers · Next step. Details stay in files and commits, not in the report.
