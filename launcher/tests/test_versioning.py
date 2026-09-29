"""Versions: VERSION, the changelog, the launcher package and the release notes
CI publishes all agree."""

import re
import subprocess
import sys
import tomllib

from conftest import REPO

VERSION = (REPO / "VERSION").read_text().strip()
NOTES = REPO / "tools/release_notes.py"


def notes(*args):
    return subprocess.run([sys.executable, str(NOTES), *args], capture_output=True, text=True)


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_changelog_leads_with_this_version_and_lists_every_one():
    versions = notes("--versions").stdout.split()
    assert versions[-1] == VERSION  # the newest entry is the version being built
    as_numbers = [tuple(map(int, v.split("."))) for v in versions]
    assert as_numbers == sorted(as_numbers) and len(set(as_numbers)) == len(as_numbers)
    assert versions[0] == "0.1.0"
    headings = re.findall(r"^## (\S+) \((\d{4}-\d{2}-\d{2})\)$", (REPO / "CHANGELOG.md").read_text(), re.M)
    assert len(headings) == len(versions)  # every version has a date


def test_launcher_package_has_the_same_version():
    project = tomllib.loads((REPO / "launcher/pyproject.toml").read_text())["project"]
    assert project["version"] == VERSION


def test_release_notes():
    r = notes(VERSION)
    assert r.returncode == 0 and r.stdout.strip().startswith("- ")
    assert notes(f"v{VERSION}").stdout == r.stdout  # a tag works too
    assert "Quick Resume" in notes("0.3.0").stdout
    assert "## " not in notes("0.19.0").stdout  # just that version's notes
    missing = notes("9.9.9")
    assert missing.returncode == 1 and "isn't in CHANGELOG.md" in missing.stderr
    assert notes().returncode == 2


def test_version_shown_by_hearth(tmp_path, monkeypatch):
    from hearth import updates

    (tmp_path / "version.json").write_text('{"version": "0.20.0", "built": "2026-09-29T17:00Z"}')
    monkeypatch.setattr(updates, "VERSION_FILE", tmp_path / "version.json")
    assert updates.hearth_version() == "0.20.0"


def test_past_releases_cover_every_earlier_version():
    rows = [line.split() for line in (REPO / "tools/past-releases.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    versions = notes("--versions").stdout.split()
    assert [r[0] for r in rows] == [f"0.{i}.0" for i in range(1, 20)]  # everything before tagging began
    assert {r[0] for r in rows} <= set(versions)
    assert all(re.fullmatch(r"[0-9a-f]{40}", r[1]) for r in rows)
