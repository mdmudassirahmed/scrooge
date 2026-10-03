import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "skills" / "receipts" / "scripts" / "audit.py"
APPLY = ROOT / "skills" / "receipts" / "scripts" / "apply.py"
FX = ROOT / "tests" / "fixtures" / "projects"


def test_audit_reads_fixture_and_recommends_cap():
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "before.json"
        r = subprocess.run([sys.executable, str(AUDIT), "--projects-dir", str(FX), "--json", str(snap)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert r.returncode == 0, r.stderr
        assert "## 1. Totals" in r.stdout and "general-purpose | inherited | 1" in r.stdout
        assert "Cap the auto-compact window" in r.stdout
        d = json.loads(snap.read_text(encoding="utf-8"))
        assert d["sessions"] == 1 and d["subagents"] == 1 and d["calls"] == 3
        r2 = subprocess.run([sys.executable, str(AUDIT), "--projects-dir", str(FX), "--compare", str(snap)],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert "## Before / after" in r2.stdout and "+0%" in r2.stdout


def test_apply_dry_run_writes_nothing():
    r = subprocess.run([sys.executable, str(APPLY), "--dry-run"], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
