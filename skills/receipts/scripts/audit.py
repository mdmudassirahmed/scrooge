#!/usr/bin/env python
"""receipts: measure Claude Code token spend from local transcripts and recommend structural fixes.

Usage: audit.py [--projects-dir DIR] [--project PATH|NAME] [--since DAYS] [--json OUT] [--compare BEFORE.json] [--out FILE] [--top N]
Prints a Markdown report. Read-only; nothing leaves the machine.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (model-id prefix, input, cache-write, cache-read, output) in USD per million tokens, API list price.
# Used only as a relative proxy for plan consumption.
RATES = [
    ("claude-fable-5", 10, 12.5, 0.25, 50), ("claude-mythos-5", 10, 12.5, 0.25, 50),
    ("claude-opus-5-5", 4, 5, 0.20, 20), ("claude-opus-5", 5, 6.25, 0.5, 25), ("claude-opus-4", 5, 6.25, 0.5, 25),
    ("claude-sonnet-5", 2, 2.5, 0.2, 10), ("claude-sonnet-4", 3, 3.75, 0.3, 15), ("claude-haiku", 1, 1.25, 0.1, 5),
]
CAPS = [200_000, 300_000, 400_000, 500_000]


def rate(model):
    for prefix, *r in RATES:
        if model.startswith(prefix):
            return r
    return RATES[2][1:]


def encode(path):
    """Claude Code's project folder name for a cwd: every non-alphanumeric char becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def blocks(msg):
    c = msg.get("content")
    return [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])


def rlen(x):
    if isinstance(x, str):
        return len(x)
    if isinstance(x, list):
        return sum(len(b.get("text", "")) if isinstance(b, dict) else len(str(b)) for b in x)
    return 0


def new_stats():
    return dict(calls=0, tokens=collections.Counter(), models=collections.Counter(), cost=0.0, max_ctx=0, ctx_sum=0,
                hist=collections.Counter(), compactions=0, tool_n=collections.Counter(), tool_chars=collections.Counter(),
                reads=collections.Counter(), read_chars=collections.Counter(), whole_reads=collections.Counter(),
                agents=collections.Counter(), agent_prompt_chars=0, handback_chars=0, text_chars=0,
                cap_saved=collections.Counter(), cache_read=0)


def scan(path):
    t = new_stats()
    t.update(path=path, cwd=None, first_prompt="", span=[None, None])
    pending = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("cwd") and not t["cwd"]:
                t["cwd"] = r["cwd"]
            ts = r.get("timestamp")
            if ts:
                t["span"][0] = t["span"][0] or ts
                t["span"][1] = ts
            if r.get("isCompactSummary") or r.get("type") == "summary":
                t["compactions"] += 1
            msg = r.get("message") or {}
            typ = r.get("type")
            if typ == "assistant":
                u = msg.get("usage") or {}
                if u:
                    m = msg.get("model", "?")
                    t["models"][m] += 1
                    t["calls"] += 1
                    ci, cw, cr, co = (u.get(k, 0) or 0 for k in
                                      ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
                    for k, v in zip(("input", "cache_write", "cache_read", "output"), (ci, cw, cr, co)):
                        t["tokens"][k] += v
                    ri, rw, rr, ro = rate(m)
                    t["cost"] += (ci * ri + cw * rw + cr * rr + co * ro) / 1e6
                    ctx = ci + cw + cr
                    t["max_ctx"] = max(t["max_ctx"], ctx)
                    t["ctx_sum"] += ctx
                    t["hist"][ctx // 100_000 * 100] += 1
                    t["cache_read"] += cr
                    for cap in CAPS:
                        if ctx > cap:
                            t["cap_saved"][cap] += min(cr, ctx - cap)
                for b in blocks(msg):
                    bt = b.get("type")
                    if bt == "text":
                        t["text_chars"] += len(b.get("text", ""))
                    elif bt == "tool_use":
                        name, inp = b.get("name"), b.get("input") or {}
                        pending[b.get("id")] = (name, inp)
                        if name == "Agent":
                            t["agents"][(inp.get("subagent_type") or "?", inp.get("model") or "inherited")] += 1
                            t["agent_prompt_chars"] += len(inp.get("prompt", ""))
                        if name == "Read" and inp.get("offset") is None and inp.get("limit") is None:
                            t["whole_reads"][str(inp.get("file_path", ""))] += 1
                        if name == "SubagentHandback":
                            t["handback_chars"] += len(json.dumps(inp))
            elif typ == "user":
                for b in blocks(msg):
                    if b.get("type") == "tool_result":
                        name, inp = pending.get(b.get("tool_use_id"), ("?", {}))
                        n = rlen(b.get("content"))
                        t["tool_n"][name] += 1
                        t["tool_chars"][name] += n
                        if name == "Read":
                            fp = str(inp.get("file_path", ""))
                            t["reads"][fp] += 1
                            t["read_chars"][fp] += n
                    elif b.get("type") == "text" and not t["first_prompt"]:
                        s = b.get("text", "").strip()
                        if s and not s.startswith("<"):
                            t["first_prompt"] = s[:110].replace("\n", " ")
    return t


def merge(ts):
    g = new_stats()
    g["cost_by_model"] = collections.Counter()
    g["n"] = len(ts)
    for t in ts:
        for k in ("calls", "cost", "ctx_sum", "compactions", "agent_prompt_chars", "handback_chars", "text_chars", "cache_read"):
            g[k] += t[k]
        for k in ("tokens", "models", "hist", "tool_n", "tool_chars", "reads", "read_chars", "whole_reads", "agents", "cap_saved"):
            g[k].update(t[k])
        g["max_ctx"] = max(g["max_ctx"], t["max_ctx"])
        if t["models"]:
            dom = max(t["models"], key=t["models"].get)
            g["cost_by_model"][dom] += t["cost"]
    return g


def fmt(n):
    return f"{n:,.0f}"


def report(top_ts, sub_ts, args):
    allts = top_ts + sub_ts
    g, gl, gs = merge(allts), merge(top_ts), merge(sub_ts)
    out = []
    P = out.append
    P(f"# receipts report  ({datetime.date.today()})")
    P(f"Transcripts: {len(top_ts)} sessions + {len(sub_ts)} subagent runs; assistant calls {fmt(g['calls'])}; "
      f"compactions seen {g['compactions']}.")
    P("Dollar figures = API list prices used as a relative proxy (plans also meter cached tokens at a reduced rate).\n")

    P("## 1. Totals")
    P("| | sessions | subagents | all |\n|---|---|---|---|")
    P(f"| API-$ equivalent | {fmt(gl['cost'])} | {fmt(gs['cost'])} | {fmt(g['cost'])} |")
    for k in ("cache_read", "cache_write", "output", "input"):
        P(f"| {k} tokens | {fmt(gl['tokens'][k])} | {fmt(gs['tokens'][k])} | {fmt(g['tokens'][k])} |")
    P(f"| avg context per call | {fmt(gl['ctx_sum'] / max(gl['calls'], 1))} | {fmt(gs['ctx_sum'] / max(gs['calls'], 1))} | "
      f"{fmt(g['ctx_sum'] / max(g['calls'], 1))} |")
    P(f"| max context | {fmt(gl['max_ctx'])} | {fmt(gs['max_ctx'])} | {fmt(g['max_ctx'])} |\n")

    P("## 2. Context size (calls per 100k bucket) and what a cap would have saved")
    P("| bucket | calls |\n|---|---|")
    for k in sorted(g["hist"]):
        P(f"| {k}k to {k + 100}k | {g['hist'][k]} |")
    P("\n| cap | cache-read tokens avoided | share of all re-reads |\n|---|---|---|")
    for cap in CAPS:
        P(f"| {cap // 1000}k | {fmt(g['cap_saved'][cap])} | {100 * g['cap_saved'][cap] / max(g['cache_read'], 1):.0f}% |")

    P("\n## 3. Model mix")
    P("| model | calls | API-$ of transcripts dominated by it |\n|---|---|---|")
    for m, n in g["models"].most_common():
        P(f"| {m} | {n} | {fmt(g['cost_by_model'][m])} |")

    P("\n## 4. Agent dispatch (subagent type, model given)")
    P("| type | model | dispatches |\n|---|---|---|")
    for (ty, md), n in g["agents"].most_common(12):
        P(f"| {ty} | {md} | {n} |")
    P(f"\nAgent prompt text typed by the parent: {fmt(g['agent_prompt_chars'])} chars; hand-back reports: {fmt(g['handback_chars'])} chars.")

    P("\n## 5. Where sessions ran, and whether project config could load")
    cwds = collections.Counter(t["cwd"] for t in top_ts if t["cwd"])
    P("| cwd | sessions | CLAUDE.md at cwd | .claude/agents at cwd |\n|---|---|---|---|")
    for c, n in cwds.most_common(8):
        has_md = os.path.exists(os.path.join(c, "CLAUDE.md"))
        has_ag = os.path.isdir(os.path.join(c, ".claude", "agents"))
        P(f"| {c} | {n} | {'yes' if has_md else 'no'} | {'yes' if has_ag else 'no'} |")

    P("\n## 6. Tool results (what came back into context)")
    P("| tool | calls | chars | ~tokens |\n|---|---|---|---|")
    for name, ch in g["tool_chars"].most_common(10):
        P(f"| {name} | {g['tool_n'][name]} | {fmt(ch)} | {fmt(ch / 4)} |")
    rep = [(fp, n) for fp, n in g["reads"].items() if n >= 3]
    redundant = sum(g["read_chars"][fp] * (n - 1) / n for fp, n in rep)
    P(f"\nFiles read 3+ times: {len(rep)}; redundant chars about {fmt(redundant)}.")
    P("| file | reads | chars |\n|---|---|---|")
    for fp, n in sorted(rep, key=lambda kv: -g["read_chars"][kv[0]])[:args.top]:
        P(f"| {fp} | {n} | {fmt(g['read_chars'][fp])} |")

    P("\n## 7. Most expensive transcripts")
    P("| API-$ | calls | max ctx | models | first prompt |\n|---|---|---|---|---|")
    for t in sorted(allts, key=lambda t: -t["cost"])[:args.top]:
        P(f"| {fmt(t['cost'])} | {t['calls']} | {fmt(t['max_ctx'])} | {dict(t['models'].most_common(2))} | {t['first_prompt'][:80]} |")

    P("\n## 8. Recommendations (rule-based, from the numbers above)")
    recs = []
    avg = g["ctx_sum"] / max(g["calls"], 1)
    share300 = g["cap_saved"][300_000] / max(g["cache_read"], 1)
    if avg > 150_000 or share300 > 0.15:
        recs.append(f"Cap the auto-compact window (CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000): average context {fmt(avg)} tokens; "
                    f"a 300k cap would have avoided {100 * share300:.0f}% of re-reads. Pair it with a SessionStart `compact` hook "
                    f"that re-injects state from disk.")
    total_disp = sum(g["agents"].values())
    inh = sum(n for (ty, md), n in g["agents"].items() if md == "inherited")
    if total_disp and inh / total_disp > 0.5:
        recs.append(f"{inh} of {total_disp} agent dispatches inherited the parent model. Pin `model:` in .claude/agents frontmatter "
                    f"(sonnet for routine roles) and pass a model in Workflow agent() calls.")
    for c, n in cwds.most_common(3):
        if c and not os.path.exists(os.path.join(c, "CLAUDE.md")):
            recs.append(f"{n} sessions ran from {c}, which has no CLAUDE.md: project rules and .claude/agents cannot load there. "
                        f"Start sessions inside the repo folder.")
    if rep:
        recs.append(f"{len(rep)} files were read 3+ times. Install the read-guard hook (apply) and split source files over 60 KB.")
    fab = sum(n for m, n in g["models"].items() if "fable" in m or "mythos" in m)
    if g["calls"] and fab / g["calls"] > 0.1:
        recs.append(f"{100 * fab / g['calls']:.0f}% of calls ran on Fable-tier models (2.5x Opus 5.5 per token); reserve them for "
                    f"tasks that need them.")
    if g["text_chars"] / 4 < 0.05 * max(g["tokens"]["output"], 1):
        recs.append("Visible assistant text is under 5% of output tokens: terseness plugins cannot save more than about 1%.")
    for i, r in enumerate(recs or ["No structural issue detected; spend tracks work volume."], 1):
        P(f"{i}. {r}")

    snap = dict(date=str(datetime.date.today()), sessions=len(top_ts), subagents=len(sub_ts), calls=g["calls"],
                cost=round(g["cost"]), cost_sessions=round(gl["cost"]), cost_subagents=round(gs["cost"]),
                avg_ctx=round(avg), max_ctx=g["max_ctx"],
                share_calls_over_300k=round(100 * sum(v for k, v in g["hist"].items() if k >= 300) / max(g["calls"], 1), 1),
                model_calls=dict(g["models"]), cost_by_model={k: round(v) for k, v in g["cost_by_model"].items()},
                inherited_dispatch_share=round(100 * inh / max(total_disp, 1)), files_read_3plus=len(rep),
                tokens=dict(g["tokens"]))
    return "\n".join(out), snap


def compare(before, now):
    rows = [("API-$ equivalent (all)", "cost"), ("API-$ sessions", "cost_sessions"), ("API-$ subagents", "cost_subagents"),
            ("avg context per call", "avg_ctx"), ("max context", "max_ctx"), ("% calls over 300k", "share_calls_over_300k"),
            ("% agent dispatches with inherited model", "inherited_dispatch_share"), ("files read 3+ times", "files_read_3plus"),
            ("assistant calls", "calls")]
    out = ["\n## Before / after", "| metric | before | after | change |", "|---|---|---|---|"]
    for label, k in rows:
        b, a = before.get(k, 0), now.get(k, 0)
        ch = f"{100 * (a - b) / b:+.0f}%" if b else "n/a"
        out.append(f"| {label} | {fmt(b)} | {fmt(a)} | {ch} |")

    def share(d, key):
        tot = sum(d.values()) or 1
        return 100 * sum(v for m, v in d.items() if key in m) / tot

    for key in ("sonnet", "opus", "fable"):
        out.append(f"| % calls on {key} | {share(before.get('model_calls', {}), key):.0f}% | "
                   f"{share(now.get('model_calls', {}), key):.0f}% | |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--project", help="cwd path or encoded project folder name")
    ap.add_argument("--since", type=float, help="only transcripts modified in the last N days")
    ap.add_argument("--json", help="save a snapshot for later --compare")
    ap.add_argument("--compare", help="snapshot file from an earlier run")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out", help="also write the report (UTF-8) to this file; avoids shell encoding issues")
    args = ap.parse_args()

    dirs = [d for d in glob.glob(os.path.join(args.projects_dir, "*")) if os.path.isdir(d)]
    if args.project:
        looks_like_path = any(ch in args.project for ch in (os.sep, "/", ":"))
        key = encode(args.project) if looks_like_path else args.project
        dirs = [d for d in dirs if os.path.basename(d) == key]
        if not dirs:
            print(f"no project folder named {key} under {args.projects_dir}")
            return
    cutoff = datetime.datetime.now().timestamp() - args.since * 86400 if args.since else None
    top, sub = [], []
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            if cutoff and os.path.getmtime(f) < cutoff:
                continue
            top.append(scan(f))
        for f in glob.glob(os.path.join(d, "*", "**", "*.jsonl"), recursive=True):
            if os.sep + "memory" + os.sep in f or (cutoff and os.path.getmtime(f) < cutoff):
                continue
            sub.append(scan(f))
    if not top and not sub:
        print("no transcripts found")
        return
    text, snap = report(top, sub, args)
    if args.compare:
        text += "\n" + compare(json.load(open(args.compare, encoding="utf-8")), snap)
    print(text)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text + "\n")
        print(f"\nreport saved: {args.out}")
    if args.json:
        json.dump(snap, open(args.json, "w", encoding="utf-8"), indent=2)
        print(f"\nsnapshot saved: {args.json}")


if __name__ == "__main__":
    main()
