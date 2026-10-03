#!/usr/bin/env python
"""receipts apply: install the structural token fixes.

  apply.py [--cap 300000] [--cleanup-days 30] [--memory-dir PATH] [--no-read-guard] [--dry-run]
      Global: edits ~/.claude/settings.json (timestamped backup first) and installs ~/.claude/hooks/read_guard.py.
  apply.py scaffold <repo> [--dry-run]
      Repo: .claude/settings.json SessionStart `compact` hook, tools/hooks/post_compact_context.py,
      CLAUDE.md token-discipline section (if missing), report of agents without a `model:` line.

Idempotent. Never commits, never deletes.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
HOME = os.path.expanduser("~")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
HOOK_DST = os.path.join(HOME, ".claude", "hooks", "read_guard.py")
READ_GUARD_CMD = 'python "' + HOOK_DST.replace("\\", "/") + '"'
POST_COMPACT_CMD = 'python "$CLAUDE_PROJECT_DIR/tools/hooks/post_compact_context.py"'
MARKER = "## Token discipline"


def has_cmd(groups, cmd):
    """True if any hook group already runs this exact command."""
    return any(hk.get("command") == cmd for g in groups for hk in g.get("hooks", []))


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, data, dry):
    if dry:
        print(f"  [dry-run] would write {path}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def apply_global(args):
    d = load_json(SETTINGS)
    before = {"cleanupPeriodDays": d.get("cleanupPeriodDays"),
              "CLAUDE_CODE_AUTO_COMPACT_WINDOW": d.get("env", {}).get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"),
              "autoMemoryDirectory": d.get("autoMemoryDirectory"),
              "read_guard_hook": has_cmd(d.get("hooks", {}).get("PreToolUse", []), READ_GUARD_CMD)}
    if os.path.exists(SETTINGS) and not args.dry_run:
        bak = SETTINGS + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(SETTINGS, bak)
        print(f"backup: {bak}")
    if args.cleanup_days is not None:
        d["cleanupPeriodDays"] = args.cleanup_days
    elif (d.get("cleanupPeriodDays") or 30) < 7:
        d["cleanupPeriodDays"] = 30
    d.setdefault("env", {})["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(args.cap)
    if args.memory_dir:
        d["autoMemoryDirectory"] = args.memory_dir.replace("\\", "/")
    if not args.no_read_guard:
        pre = d.setdefault("hooks", {}).setdefault("PreToolUse", [])
        if not before["read_guard_hook"]:
            pre.append({"matcher": "Read", "hooks": [{"type": "command", "command": READ_GUARD_CMD, "timeout": 10}]})
        if not args.dry_run:
            os.makedirs(os.path.dirname(HOOK_DST), exist_ok=True)
            shutil.copy(os.path.join(HERE, "read_guard.py"), HOOK_DST)
        print(f"read-guard hook: {HOOK_DST}")
    save_json(SETTINGS, d, args.dry_run)
    after = {"cleanupPeriodDays": d.get("cleanupPeriodDays"),
             "CLAUDE_CODE_AUTO_COMPACT_WINDOW": d["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"],
             "autoMemoryDirectory": d.get("autoMemoryDirectory"),
             "read_guard_hook": not args.no_read_guard or before["read_guard_hook"]}
    print("before:", json.dumps(before))
    print("after: ", json.dumps(after))
    print("Takes effect for new sessions. Running sessions keep their startup values.")


def scaffold(repo, dry):
    repo = os.path.abspath(repo)
    if not os.path.isdir(repo):
        sys.exit(f"not a directory: {repo}")
    # 1. repo-level SessionStart compact hook
    sp = os.path.join(repo, ".claude", "settings.json")
    d = load_json(sp)
    ss = d.setdefault("hooks", {}).setdefault("SessionStart", [])
    if not has_cmd(ss, POST_COMPACT_CMD):
        ss.append({"matcher": "compact", "hooks": [{"type": "command", "command": POST_COMPACT_CMD, "timeout": 90}]})
        save_json(sp, d, dry)
        print(f"hook added: {sp}")
    else:
        print(f"hook already present: {sp}")
    # 2. the hook script
    dst = os.path.join(repo, "tools", "hooks", "post_compact_context.py")
    if not os.path.exists(dst):
        if not dry:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(os.path.join(SKILL, "templates", "post_compact_context.py"), dst)
        print(f"script added: {dst}")
    else:
        print(f"script already present: {dst}")
    # 3. CLAUDE.md section
    md = os.path.join(repo, "CLAUDE.md")
    existing = open(md, encoding="utf-8").read() if os.path.exists(md) else ""
    if MARKER not in existing:
        section = open(os.path.join(SKILL, "templates", "CLAUDE-token-discipline.md"), encoding="utf-8").read()
        if not dry:
            with open(md, "a", encoding="utf-8") as fh:
                fh.write(("\n" if existing and not existing.endswith("\n") else "") + "\n" + section)
        print(f"CLAUDE.md section appended: {md}")
    else:
        print("CLAUDE.md already has the token-discipline section")
    # 4. agents without a model line (report only; the model choice belongs to the user)
    agents_dir = os.path.join(repo, ".claude", "agents")
    if os.path.isdir(agents_dir):
        missing = []
        for f in sorted(os.listdir(agents_dir)):
            if not f.endswith(".md"):
                continue
            text = open(os.path.join(agents_dir, f), encoding="utf-8").read()
            fm = re.match(r"^---\n(.*?)\n---", text, re.S)
            if not fm or not re.search(r"^model:\s*\S+", fm.group(1), re.M):
                missing.append(f)
        print(f"agents without model: {missing or 'none'}  (see templates/agent-model-tiers.md)")
    else:
        print("no .claude/agents folder: agents are the main lever for model tiering; see templates/agent-model-tiers.md")
    print("Nothing was committed. Review with `git status` and commit when you are ready.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", default="global", choices=["global", "scaffold"])
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--cap", type=int, default=300_000)
    ap.add_argument("--cleanup-days", type=int)
    ap.add_argument("--memory-dir")
    ap.add_argument("--no-read-guard", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.mode == "scaffold":
        if not args.repo:
            sys.exit("usage: apply.py scaffold <repo>")
        scaffold(args.repo, args.dry_run)
    else:
        apply_global(args)


if __name__ == "__main__":
    main()
