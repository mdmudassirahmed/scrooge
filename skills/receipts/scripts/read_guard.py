#!/usr/bin/env python
"""PreToolUse hook (matcher: Read).
Refuses a single whole-file Read of a large *text* file and tells Claude to slice (offset/limit) or Grep instead.
Nothing is withheld: the same file can still be read completely, in pieces.
Threshold: READ_GUARD_MAX_BYTES (default 40960 = 40 KB, roughly 10k tokens). Images/PDF/notebooks are exempt.
Input: Claude Code hook JSON on stdin. Output: deny JSON when the rule triggers; silence otherwise (= allow)."""
import json, os, sys

LIMIT = int(os.environ.get("READ_GUARD_MAX_BYTES", "40960"))
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".pdf", ".ipynb"}

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Read":
        return
    ti = data.get("tool_input") or {}
    fp = ti.get("file_path") or ""
    if not fp or ti.get("offset") is not None or ti.get("limit") is not None:
        return
    if os.path.splitext(fp)[1].lower() in SKIP_EXT:
        return
    try:
        size = os.path.getsize(fp)
    except OSError:
        return
    if size <= LIMIT:
        return
    reason = (f"read-guard: {os.path.basename(fp)} is {size // 1024} KB (about {size // 4:,} tokens). "
              f"Whole-file reads over {LIMIT // 1024} KB are refused because every byte would stay in context for the rest of the session. "
              "Use Grep to locate the relevant section, then Read with offset and limit (for example limit=200), or read in slices. "
              "Nothing is withheld; the full file is still available piece by piece.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))

main()
