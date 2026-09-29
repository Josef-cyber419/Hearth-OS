"""Progress reports: one per version, made by tools/progress_report.py."""

import json
import subprocess
import sys
import tomllib

from conftest import REPO

VERSION = (REPO / "VERSION").read_text().strip()
TOOL = REPO / "tools/progress_report.py"


def test_this_version_has_a_report():
    # When VERSION goes up, run tools/progress_report.py (see reports/README.md).
    report = REPO / "reports" / VERSION / "report.md"
    assert report.exists(), f"no progress report for {VERSION}: run python3 tools/progress_report.py"
    text = report.read_text()
    assert f"# Hearth OS {VERSION}" in text and "Lines of code" in text
    assert f"[{VERSION}]({VERSION}/report.md)" in (REPO / "reports/README.md").read_text()


def test_status_file_is_valid():
    status = tomllib.loads((REPO / "reports/status.toml").read_text())
    assert status["summary"] and status["next"]
    assert {a["status"] for a in status["area"]} <= {"confirmed", "shipped", "next", "not-possible"}


def test_counts_this_tree():
    r = subprocess.run([sys.executable, str(TOOL), "--stats"], capture_output=True, text=True, check=True)
    stats = json.loads(r.stdout)
    assert stats["version"] == VERSION
    assert stats["code"] > 1000 and stats["tests"] > 100 and stats["guides"] >= 10
    assert stats["code"] == sum(n for part, n in stats["areas"].items() if part != "Tests")
