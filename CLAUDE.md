# Working on Hearth OS

Hearth OS is a TV-style home screen for a living-room PC, shipped as a
Bazzite bootc image. Read README.md first; docs/ARCHITECTURE.md explains how
the pieces fit.

## Two kinds of session

Claude works on this project from two places. Work out which one you are
before doing anything:

- **The cloud session** (a container with no display, no hardware and no
  route to the PC). It does development: features, fixes, tests, docs,
  pull requests and releases. You're here if `/usr/libexec/hearth` doesn't
  exist and `hearthctl` isn't installed.
- **The field session** (Claude Code on the living-room PC itself, usually
  over SSH, in `~/hearth-os`). It diagnoses and tests on the real hardware,
  and reports what it finds. You're here if `hearthctl status` works.

### Handing work between them: field reports

The owner shouldn't have to copy text between sessions. The field session
files what it finds as a **GitHub issue labelled `field-report`**, and the
cloud session reads open `field-report` issues when asked to "check field
reports" (and before starting new work).

A field report is one issue per problem (or one per checklist run), titled
plainly ("Update reports failed while a download is running"), with:

- what the owner saw, and what was expected;
- the evidence: command output and log lines, trimmed to what matters;
- the Hearth version (`hearthctl status`) and the date;
- the likely cause, if known, and a proposed fix.

The field session files them with `gh issue create --label field-report`.
One-time setup on the PC: `gh` (`brew install gh` if it's missing), then
`gh auth login`, then `gh label create field-report --color d93f0b` if the
label doesn't exist yet. The cloud session fixes them, ships
the fix through the normal release flow, and closes the issue naming the
version that fixed it. The field session then checks it on the PC after
the update.

## Rules for the field session (on the PC)

This PC is the family TV. Treat it gently:

- **Ask before anything that changes the system**: sudo commands, installing
  or removing apps, editing files outside `~/hearth-os`, rebooting, logging
  out of Game Mode. Reading logs and running `hearthctl` read-only commands
  (status, doctor, logs, events, footprint) needs no permission.
- **You can't type the owner's password.** For a root command, ask them to
  run it in the session with a leading `!` (e.g. `! sudo bootc status`), and
  read the output that comes back. `sudo /usr/libexec/hearth/hearth-update apply`
  is allowed without a password.
- **Don't take over the screen** while someone might be watching or playing:
  ask before launching apps, sending key presses, or restarting Game Mode.
- **Don't push to `main`**, and don't push to `staging` either: that's the
  cloud session's release branch. To propose a code change, push a branch
  named `field/<short-topic>` and open a pull request into `staging`, or
  describe the patch in the field report.
- **Try code changes live without a new image**: `hearthctl dev ~/hearth-os/launcher`
  makes Game Mode run the launcher from this checkout (restart Game Mode to
  apply); `hearthctl dev --off` goes back to the built-in one. Changes under
  `image/` (scripts, services, udev rules) only take effect in a new image.
- **Don't build the OS image here** (it's 7 GB and the disk is 256 GB):
  GitHub Actions builds it.

Useful on the PC:

| Command | For |
|---|---|
| `hearthctl status` / `doctor` | version, what's running, setup problems |
| `hearthctl logs -n 200` / `events` | Hearth's log and its timeline |
| `hearthctl footprint` | memory and CPU in use |
| `hearthctl screenshot` | what's on the TV, into ~/Pictures/Hearth (look at the PNG) |
| `journalctl -b -u uupd --no-pager` | the OS updater |
| `bootc status` (sudo) | booted, staged and rollback images |
| `hearth-cec status` / `vendor` | the TV over HDMI-CEC (with an adapter) |

### After each update: the checklist

Run these and file one field report with pass or fail for each (plus
details for anything that fails):

1. `hearthctl status` shows the new version; `hearthctl doctor` has no errors.
2. `hearthctl footprint` after a minute idle: Hearth under 2% CPU, around 300 MB.
3. `hearthctl screenshot` of the home screen looks right (look at the image).
4. The changelog's items for this version, one by one, as far as they can be
   checked without taking over the TV.
5. `journalctl --user -p warning -b --no-pager | grep -i hearth` has nothing new.

## Rules for the cloud session (development)

- **Branches**: work on `staging`; open a pull request `staging` → `main`
  and merge it once CI (tests + image build) is green. `main` is what every
  PC installs; after each merge CI moves `staging` to match `main` (merge
  `origin/staging` before the next push). Never push to `main` directly.
- **Versions**: every change that ships bumps `VERSION` and
  `launcher/pyproject.toml` (minor for features, patch for fixes), adds a
  dated `CHANGELOG.md` entry (short bullets in plain words: the home screen
  shows them after the update), and a progress report:
  `python3 tools/progress_report.py` (update `reports/status.toml` first).
  Tests check all three agree. CI publishes the GitHub release and the image
  tag.
- **Before pushing**:
  ```sh
  cd launcher && ruff check . && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q
  ```
  and shellcheck on any shell script changed (the list is in
  `.github/workflows/build.yml`). New behaviour gets a test. Screens that
  change get a rendered screenshot, looked at, before shipping.
- **Nothing is "done" until it's been on the real PC**: say what was only
  tested in a virtual display, and ask the field session (via the owner) to
  check it.

## Code

- `launcher/hearth/`: the home screen (`ui.py`), Quick Menu (`overlay.py`,
  `quickmenu*.py`), Settings (`settings_app.py`), session hub (`hub.py`),
  `hearthctl` (`ctl.py`), and one module per feature.
- `launcher/tests/`: headless tests (pygame's dummy video driver); `test_e2e.py`
  runs the real hub under Xvfb.
- `image/system_files/`: files laid into the image as `/` (scripts in
  `usr/libexec/hearth/`, the default tiles in `usr/share/hearth/apps.toml`).
- Match the surrounding code: small modules, docstrings that say what a
  thing is for, comments only where the why isn't obvious.
- User-facing text (tiles, Settings, notices, docs) is short and plain, for
  someone on a sofa with a controller: no jargon, no exclamation marks.
- Hearth runs on AMD and Intel graphics; NVIDIA is out of scope for now.
