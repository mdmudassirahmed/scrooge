#!/usr/bin/env python
"""SessionStart hook (matcher: compact), installed by /receipts scaffold.

After every context compaction, print a small, exact state block that Claude Code appends to the context,
so the facts come from disk instead of from the summary. Bounded to about 6 KB.

Optional config next to this file, post_compact_context.json:
  {"commands": [["python", "tools/tracker.py", "summary"]], "files": ["docs/HANDOFF.md", "docs/STATUS.md"]}
Without it: git state plus the newest "## " section of docs/HANDOFF.md or the top of docs/STATUS.md, whichever exists.
Test standalone:  python tools/hooks/post_compact_context.py
"""
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(HERE))
os.chdir(ROOT)
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
CAP_CMD, CAP_FILE = 1800, 3000


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=ENV).stdout.strip()
    except Exception as e:
        return f"(unavailable: {e})"


def newest_section(text):
    m = re.search(r"^## .*?(?=^## |\Z)", text, re.S | re.M)
    return (m.group(0) if m else text).strip()


cfg_path = os.path.join(HERE, "post_compact_context.json")
cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
out = ["[post-compaction state, re-read from disk by tools/hooks/post_compact_context.py; trust this over the summary]"]
for cmd in cfg.get("commands", []):
    out.append(f"## {' '.join(cmd)}")
    out.append(run(cmd)[:CAP_CMD])
files = cfg.get("files") or [f for f in ("docs/HANDOFF.md", "docs/STATUS.md", "HANDOFF.md", "STATUS.md") if os.path.exists(f)][:1]
for f in files:
    if os.path.exists(f):
        out.append(f"## {f}, newest section")
        out.append(newest_section(open(f, encoding="utf-8", errors="replace").read())[:CAP_FILE])
out.append("## Git")
out.append(run(["git", "log", "-1", "--oneline"]))
status = run(["git", "status", "--short"]).splitlines()
out.append("\n".join(status[:15]) + (f"\n... {len(status) - 15} more" if len(status) > 15 else "") if status else "(working tree clean)")
out.append("Next: re-read the current task's spec file before continuing; do not assume a step was done without evidence.")
print("\n".join(out))
