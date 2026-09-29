#!/usr/bin/env python3
"""The progress report for a version, and the history of every version.

    python3 tools/progress_report.py            # report for the version in VERSION
    python3 tools/progress_report.py --stats    # just this tree's numbers, as JSON

Writes reports/<version>/report.md (and report.pdf, if reportlab is
installed) and refreshes the history table in reports/README.md. The numbers
(lines of code, tests, docs) come from the files themselves: the working tree
for the current version, git for past ones. What's working, open issues and
what's next come from reports/status.toml, so edit that first. Screenshots in
reports/<version>/screens/ go in the report too.

Run it whenever VERSION goes up (a test checks the report exists).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORTS = REPO / "reports"
PAST = REPO / "tools/past-releases.txt"

# What the lines are, by path. Docs are counted apart from code.
AREAS = [
    ("Home screen, Quick Menu and settings (Python)",
     lambda p: p.startswith("launcher/hearth/") and p.endswith(".py")),
    ("System image (scripts, services, config)",
     lambda p: (p.startswith("image/") or p == "Containerfile") and not p.endswith(".md")),
    ("Build and tools", lambda p: p.startswith((".github/", "tools/")) and not p.endswith(".md")),
    ("Tests", lambda p: p.startswith("launcher/tests/") and p.endswith(".py")),
]
LEGEND = ("**Confirmed** means reported working on the real PC; **Shipped** means built, tested and released, "
          "but not yet reported on.")
STATUS = {
    "confirmed": ("✅", "Confirmed on the PC"),
    "shipped": ("🟡", "Shipped"),
    "next": ("⚪", "Not started"),
    "not-possible": ("⛔", "Not possible"),
}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


# -- counting ---------------------------------------------------------------------


def _is_doc(path: str) -> bool:
    return path.endswith(".md") and not path.startswith("reports/")


def count(files: dict[str, bytes]) -> dict:
    """Lines (not counting blank ones) by area, tests and docs, for a tree."""
    areas = {name: 0 for name, _ in AREAS}
    tests = docs = guides = 0
    for path, data in files.items():
        if b"\0" in data[:4096]:
            continue  # images, fonts
        text = data.decode("utf-8", "replace")
        lines = sum(1 for line in text.splitlines() if line.strip())
        if _is_doc(path):
            docs += lines
            guides += path.startswith("docs/")
            continue
        for name, match in AREAS:
            if match(path):
                areas[name] += lines
                break
        if path.startswith("launcher/tests/") and path.endswith(".py"):
            tests += len(re.findall(r"^\s*(?:async )?def test_", text, re.M))
    code = sum(n for name, n in areas.items() if name != "Tests")
    return {"code": code, "areas": areas, "tests": tests, "docs": docs, "guides": guides}


def tree_files() -> dict[str, bytes]:
    """The working tree, as git would see it (ignored files left out)."""
    out = {}
    for path in git("ls-files", "-co", "--exclude-standard", "-z").split("\0"):
        full = REPO / path
        if path and full.is_file():
            out[path] = full.read_bytes()
    return out


def rev_files(rev: str) -> dict[str, bytes]:
    listing = git("ls-tree", "-r", "-z", rev).split("\0")
    entries = [(e.split()[2], e.split("\t", 1)[1]) for e in listing if e and e.split()[1] == "blob"]
    batch = subprocess.run(["git", "-C", str(REPO), "cat-file", "--batch"], check=True, capture_output=True,
                           input="".join(f"{sha}\n" for sha, _ in entries).encode()).stdout
    out, pos = {}, 0
    for _sha, path in entries:
        end = batch.index(b"\n", pos)
        size = int(batch[pos:end].split()[2])
        out[path] = batch[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return out


def prs_in(rev: str) -> int:
    subjects = git("log", "--first-parent", "--format=%s", rev)
    return len(set(re.findall(r"#(\d+)", subjects)))


# -- versions ---------------------------------------------------------------------


def changelog_dates() -> dict[str, str]:
    text = (REPO / "CHANGELOG.md").read_text()
    return dict(re.findall(r"^## (\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)$", text, re.M))


def changes(version: str) -> list[str]:
    """That version's CHANGELOG bullets, as written."""
    out, inside = [], False
    for line in (REPO / "CHANGELOG.md").read_text().splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.split()[1] == version
        elif inside and line.startswith(("- ", "* ")):
            out.append(line[2:].strip())
        elif inside and line.strip() and out:
            out[-1] += " " + line.strip()
    return out


def released_commits() -> dict[str, str]:
    """version -> the commit on main it was released as."""
    out = {}
    for line in PAST.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            version, commit = line.split()
            out[version] = commit
    ref = "origin/main"
    try:
        git("rev-parse", "--verify", "--quiet", ref)
    except subprocess.CalledProcessError:
        ref = "HEAD"
    # Newer versions: the first commit on main where VERSION said so.
    for commit in reversed(git("log", "--first-parent", "--format=%H", ref, "--", "VERSION").split()):
        try:
            version = git("show", f"{commit}:VERSION").strip()
        except subprocess.CalledProcessError:
            continue
        out.setdefault(version, commit)
    return out


def history(current: str, current_stats: dict) -> list[dict]:
    dates = changelog_dates()
    rows = []
    for version, commit in released_commits().items():
        if version == current:
            continue
        try:
            stats = count(rev_files(commit))
            stats["prs"] = prs_in(commit)
        except subprocess.CalledProcessError:
            continue  # not in this clone
        rows.append({"version": version, "date": dates.get(version, ""), **stats})
    rows.append({"version": current, "date": dates.get(current, ""), **current_stats})
    return sorted(rows, key=lambda r: key(r["version"]))


# -- writing ----------------------------------------------------------------------


def n(value: int) -> str:
    return f"{value:,}"


def delta(now: int, before: int | None) -> str:
    if before is None or now == before:
        return ""
    return f" ({'+' if now > before else '−'}{n(abs(now - before))})"


def long_date(iso: str) -> str:
    if not iso:
        return ""
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def link_for(version: str) -> str | None:
    folder = REPORTS / version
    for name in ("report.md", "report.pdf"):
        if (folder / name).exists():
            return f"{version}/{name}"
    return None


def history_table(rows: list[dict], prefix: str = "") -> list[str]:
    out = ["| Version | Date | Lines of code | Tests | Docs (lines) | Guides | Pull requests |",
           "|---|---|--:|--:|--:|--:|--:|"]
    for r in reversed(rows):
        link = link_for(r["version"])
        name = f"[{r['version']}]({prefix}{link})" if link else r["version"]
        out.append(f"| {name} | {r['date']} | {n(r['code'])} | {n(r['tests'])} | {n(r['docs'])} "
                   f"| {r['guides']} | {r['prs']} |")
    return out


def markdown(version: str, rows: list[dict], status: dict, screens: list[Path]) -> str:
    now = rows[-1]
    before = rows[-2] if len(rows) > 1 else None
    b = (lambda k: before[k]) if before else (lambda k: None)
    since = f" since {before['version']}" if before else ""
    out = [f"# Hearth OS {version}: progress report", "",
           f"_{long_date(now['date'])} · made by `tools/progress_report.py`_", "",
           " ".join(status["summary"].split()), "",
           f"Tested on: {status['reference_pc']}.", "",
           "## At a glance", "",
           f"| | {version} | Change{since} |", "|---|--:|--:|",
           f"| Lines of code | {n(now['code'])} | {delta(now['code'], b('code')).strip(' ()') or '–'} |",
           f"| Automated tests | {n(now['tests'])} | {delta(now['tests'], b('tests')).strip(' ()') or '–'} |",
           f"| Lines of docs | {n(now['docs'])} | {delta(now['docs'], b('docs')).strip(' ()') or '–'} |",
           f"| Guides in docs/ | {now['guides']} | {delta(now['guides'], b('guides')).strip(' ()') or '–'} |",
           f"| Pull requests merged | {now['prs']} | |",
           f"| Versions released | {len(rows)} | |", "",
           "Lines of code by part (blank lines not counted):", "",
           "| Part | Lines |", "|---|--:|"]
    out += [f"| {name} | {n(lines)} |" for name, lines in now["areas"].items()]
    out += ["", f"## What's new in {version}", ""]
    out += [f"- {c}" for c in changes(version)] or ["- (no changelog entry)"]
    out += ["", "## What's working", "", "| Area | What it does | Status |", "|---|---|---|"]
    for a in status["area"]:
        icon, words = STATUS[a["status"]]
        note = f" ({a['note']})" if a.get("note") else ""
        new = " **new**" if a.get("since") == version else ""
        out.append(f"| {a['name']}{new} | {a['what']} | {icon} {words}{note} |")
    out += ["", LEGEND]
    if screens:
        out += ["", "## Screenshots", ""]
        for shot in screens:
            caption = status.get("screens", {}).get(shot.name, shot.stem.replace("-", " ").capitalize())
            out += [f"![{caption}](screens/{shot.name})", f"_{caption}_", ""]
        out.pop()
    out += ["", "## Open issues", "", "| Issue | Where it stands | What's needed |", "|---|---|---|"]
    out += [f"| {i['what']} | {i['state']} | {i['needs']} |" for i in status.get("issue", [])]
    out += ["", "## Next", ""] + [f"- {x}" for x in status.get("next", [])]
    out += ["", "## Every version", ""] + history_table(rows, "../") + [""]
    return "\n".join(out)


def index(rows: list[dict]) -> str:
    latest = rows[-1]["version"]
    return "\n".join([
        "# Progress reports", "",
        f"One report per version: numbers, what's working, what's new, open issues. Latest: "
        f"**[{latest}]({link_for(latest)})**.", "",
        "## History", "",
        "Every version, counted from the code as it was released. Lines of code don't count blank lines; tests "
        "are the automated test functions; pull requests are those merged by then.", "",
        *history_table(rows), "",
        "## Making the next one", "",
        "When `VERSION` goes up: update `reports/status.toml` (what's working, issues, next), put any screenshots "
        "in `reports/<version>/screens/`, then run", "",
        "```sh", "python3 tools/progress_report.py", "```", "",
        "It writes `reports/<version>/report.md` (and `report.pdf` when reportlab is installed) and this table.",
        "",
    ])


def pdf(path: Path, version: str, rows: list[dict], status: dict, screens: list[Path]) -> bool:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return False
    orange, blue, ink = colors.HexColor("#f2862e"), colors.HexColor("#8fc1e3"), colors.HexColor("#1b2330")
    muted, line, soft = colors.HexColor("#5b6675"), colors.HexColor("#d9dee5"), colors.HexColor("#f4f6f9")
    tone = {"confirmed": "#2e7d4f", "shipped": "#b86e00", "next": "#6b7280", "not-possible": "#6b7280"}
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=26, leading=30,
                        textColor=ink, alignment=0, spaceAfter=4)
    sub = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=11, textColor=muted, leading=15)
    h2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=15, textColor=ink,
                        spaceBefore=14, spaceAfter=6)
    body = ParagraphStyle("B", parent=ss["Normal"], fontSize=10, leading=14, textColor=ink)
    small = ParagraphStyle("SM", parent=body, fontSize=8.5, leading=11, textColor=muted)
    cell = ParagraphStyle("CELL", parent=body, fontSize=8.8, leading=11.2)
    bold = ParagraphStyle("CELLB", parent=cell, fontName="Helvetica-Bold")
    bullet = ParagraphStyle("BUL", parent=body, leftIndent=12, bulletIndent=2)

    def md(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        return re.sub(r"`([^`]+)`", r"<i>\1</i>", text)

    def p(text, style=body):
        return Paragraph(text, style)

    def table(data, widths, align_right=()):
        t = Table([[p(c, bold if r == 0 else cell) for c in row] for r, row in enumerate(data)],
                  colWidths=widths, repeatRows=1)
        st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, line),
              ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
              ("BACKGROUND", (0, 0), (-1, 0), soft), ("LINEBELOW", (0, 0), (-1, 0), 1, ink)]
        t.setStyle(TableStyle(st))
        return t

    now = rows[-1]
    before = rows[-2] if len(rows) > 1 else None
    width = letter[0] - 1.5 * inch

    def growth(rows, w):
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.shapes import Drawing

        d = Drawing(w, 150)
        chart = VerticalBarChart()
        chart.x, chart.y, chart.width, chart.height = 36, 22, w - 46, 118
        chart.data = [[r["code"] for r in rows], [r["tests"] * 10 for r in rows]]
        chart.categoryAxis.categoryNames = [r["version"].rsplit(".", 1)[0] for r in rows]
        chart.categoryAxis.labels.fontSize = 6.5
        chart.valueAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labelTextFormat = lambda v: f"{v / 1000:g}k"
        chart.bars[0].fillColor, chart.bars[1].fillColor = orange, blue
        chart.bars.strokeColor = None
        chart.groupSpacing, chart.barSpacing = 3, 0
        d.add(chart)
        return d

    def page(c, doc):
        c.saveState()
        c.setFillColor(orange)
        c.rect(0, letter[1] - 10, letter[0], 6, stroke=0, fill=1)
        c.setFillColor(blue)
        c.rect(0, letter[1] - 14, letter[0], 3, stroke=0, fill=1)
        c.setFont("Helvetica", 8)
        c.setFillColor(muted)
        c.drawString(0.75 * inch, 0.5 * inch, f"Hearth OS {version} · progress report · {long_date(now['date'])}")
        c.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, str(doc.page))
        c.restoreState()

    s = [p("Hearth OS", h1), p(f"Progress report · version {version} · {long_date(now['date'])}", sub),
         Spacer(1, 8), p(" ".join(status["summary"].split())), Spacer(1, 8)]
    boxes = [(n(now["code"]), "lines of code"), (n(now["tests"]), "automated tests"),
             (str(len(rows)), "versions released"), (str(now["prs"]), "pull requests merged"),
             (str(now["guides"]), "guides in docs/")]
    figures = Table([[p(f'<font size="20" color="#f2862e"><b>{v}</b></font>', cell) for v, _ in boxes],
                     [p(label, small) for _, label in boxes]], colWidths=[width / 5] * 5)
    figures.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), soft), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    s += [figures, Spacer(1, 4)]
    if before:
        s += [p(f"Since {before['version']}: code {delta(now['code'], before['code']).strip(' ()') or 'unchanged'}, "
                f"tests {delta(now['tests'], before['tests']).strip(' ()') or 'unchanged'}. "
                f"Tested on: {status['reference_pc']}.", small)]
    s += [p(f"What's new in {version}", h2)]
    s += [Paragraph(md(c), bullet, bulletText="•") for c in changes(version)]
    s += [p("What's working", h2)]
    data = [["Area", "What it does", "Status"]]
    for a in status["area"]:
        note = f"<br/>({a['note']})" if a.get("note") else ""
        data.append([md(a["name"]), md(a["what"]),
                     f'<font color="{tone[a["status"]]}"><b>{STATUS[a["status"]][1]}</b></font>{note}'])
    s += [table(data, [1.4 * inch, 4.1 * inch, 1.5 * inch]), Spacer(1, 3), p(LEGEND.replace("**", ""), small)]
    if screens:
        s += [p("Screenshots", h2)]
        half = width / 2 - 6
        cells = []
        for shot in screens:
            iw, ih = ImageReader(str(shot)).getSize()
            caption = status.get("screens", {}).get(shot.name, shot.stem)
            cells.append([Image(str(shot), width=half, height=half * ih / iw), Spacer(1, 3), p(md(caption), small)])
        grid = [cells[i:i + 2] + [[]] * (2 - len(cells[i:i + 2])) for i in range(0, len(cells), 2)]
        t = Table(grid, colWidths=[width / 2, width / 2])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        s += [t]
    s += [KeepTogether([p("Lines of code by part", h2),
                        table([["Part", "Lines"]] + [[name, n(v)] for name, v in now["areas"].items()],
                              [5.5 * inch, 1.5 * inch])])]
    s += [KeepTogether([p("Growth", h2), growth(rows, width), p("Lines of code (orange) and automated tests "
                                                                   "(blue, ×10) at each version.", small)])]
    if status.get("issue"):
        s += [p("Open issues", h2)]
        s += [table([["Issue", "Where it stands", "What's needed"]]
                    + [[md(i["what"]), md(i["state"]), md(i["needs"])] for i in status["issue"]],
                    [2.0 * inch, 2.7 * inch, 2.3 * inch])]
    s += [p("Next", h2)] + [Paragraph(md(x), bullet, bulletText="•") for x in status.get("next", [])]
    hist = [["Version", "Date", "Lines of code", "Tests", "Docs (lines)", "Pull requests"]]
    hist += [[r["version"], r["date"], n(r["code"]), n(r["tests"]), n(r["docs"]), str(r["prs"])]
             for r in reversed(rows)]
    s += [KeepTogether([p("Every version", h2), table(hist, [1.0 * inch, 1.2 * inch] + [1.2 * inch] * 4)])]
    SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      topMargin=0.7 * inch, bottomMargin=0.75 * inch, title=f"Hearth OS {version} progress report",
                      author="Hearth OS").build(s, onFirstPage=page, onLaterPages=page)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stats", action="store_true", help="print this tree's numbers as JSON")
    args = ap.parse_args()
    version = (REPO / "VERSION").read_text().strip()
    stats = count(tree_files())
    stats["prs"] = prs_in("HEAD")
    if args.stats:
        print(json.dumps({"version": version, **stats}, indent=2))
        return 0
    status = tomllib.loads((REPORTS / "status.toml").read_text())
    rows = history(version, stats)
    folder = REPORTS / version
    folder.mkdir(parents=True, exist_ok=True)
    order = list(status.get("screens", {}))
    screens = sorted((folder / "screens").glob("*.png"),
                     key=lambda f: (order.index(f.name) if f.name in order else len(order), f.name))
    (folder / "report.md").write_text(markdown(version, rows, status, screens))
    made_pdf = pdf(folder / "report.pdf", version, rows, status, screens)
    (REPORTS / "README.md").write_text(index(rows))
    print(f"reports/{version}/report.md" + (" and report.pdf" if made_pdf else " (no PDF: pip install reportlab)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
