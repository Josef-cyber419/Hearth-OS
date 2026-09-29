"""The TV over HDMI-CEC: one-touch play and its make (hearth-cec)."""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import REPO
from hearth import tv

CEC = REPO / "image/system_files/usr/libexec/hearth/hearth-cec"


@pytest.fixture(autouse=True)
def fresh():
    tv._last = -1e9


def test_switch_here_only_with_an_adapter_and_not_too_often(tmp_path):
    calls = []
    run = lambda args, **kw: calls.append((args, kw["env"]["HEARTH_CEC_TRIES"]))  # noqa: E731
    assert not tv.switch_here(device=tmp_path / "cec0", run=run, now=100.0)  # no adapter
    (tmp_path / "cec0").touch()
    assert tv.switch_here(tries=5, device=tmp_path / "cec0", run=run, now=100.0)
    assert not tv.switch_here(device=tmp_path / "cec0", run=run, now=110.0)  # just asked
    assert tv.switch_here(device=tmp_path / "cec0", run=run, now=100.0 + tv.NUDGE_SECONDS)
    assert calls == [([tv.HELPER, "switch"], "5"), ([tv.HELPER, "switch"], "1")]


def fake_tv(tmp_path: Path, answers_on_try: int, vendor: str = "LG") -> dict:
    """A cec-ctl that logs what it's asked; the TV says it's on from the
    given try (0: never)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (tmp_path / "cec0").touch()
    count = tmp_path / "count"
    count.write_text("0")
    (bin_ / "cec-ctl").write_text(f"""#!/usr/bin/bash
echo "$*" >> {tmp_path}/log
case "$*" in
  *--image-view-on*) echo $(( $(cat {count}) + 1 )) > {count} ;;
  *--give-device-power-status*)
     if [[ {answers_on_try} -gt 0 && $(cat {count}) -ge {answers_on_try} ]]; then
       echo "		pwr-state: on (0x00)"; else echo "		pwr-state: standby (0x01)"; fi ;;
  *--give-device-vendor-id*) echo "		vendor-id: 0x00e091 ({vendor})" ;;
  "-d {tmp_path}/cec0") echo "	Physical Address           : 1.0.0.0" ;;
esac
""")
    (bin_ / "cec-ctl").chmod(0o755)
    return {"PATH": f"{bin_}:/usr/bin:/bin", "HEARTH_CEC_DEVICE": str(tmp_path / "cec0"),
            "HEARTH_CEC_DELAY": "0", "HOME": str(tmp_path)}


def calls(tmp_path: Path) -> list[str]:
    return (tmp_path / "log").read_text().splitlines()


def test_switch_keeps_asking_until_the_tv_is_on(tmp_path):
    env = fake_tv(tmp_path, answers_on_try=3)
    r = subprocess.run([str(CEC), "switch"], env=env, capture_output=True, text=True)
    assert r.returncode == 0
    log = calls(tmp_path)
    assert sum("--image-view-on" in c for c in log) == 3
    active = [c for c in log if "--active-source" in c]
    assert len(active) == 4 and all("phys-addr=1.0.0.0" in c for c in active)  # each try, then once more


def test_switch_gives_up_and_says_why(tmp_path):
    env = {**fake_tv(tmp_path, answers_on_try=0), "HEARTH_CEC_TRIES": "2"}
    r = subprocess.run([str(CEC), "switch"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "CEC on in its settings" in r.stderr
    assert sum("--image-view-on" in c for c in calls(tmp_path)) == 2


def test_wake_respects_the_setting_but_switch_does_not(tmp_path):
    env = fake_tv(tmp_path, answers_on_try=1)
    conf = tmp_path / "cec.conf"
    conf.write_text("TV_WAKE=0\n")
    # A copy of the script that reads this cec.conf instead of /etc/hearth's.
    text = CEC.read_text().replace("/etc/hearth/cec.conf", str(conf))
    script = tmp_path / "hearth-cec"
    script.write_text(text)
    script.chmod(0o755)
    assert subprocess.run([str(script), "wake"], env=env).returncode == 0
    assert not (tmp_path / "log").exists()  # TV_WAKE=0: left alone
    assert subprocess.run([str(script), "switch"], env=env).returncode == 0
    assert any("--image-view-on" in c for c in calls(tmp_path))


def test_vendor(tmp_path):
    env = fake_tv(tmp_path, answers_on_try=1, vendor="Samsung")
    out = subprocess.run([str(CEC), "vendor"], env=env, capture_output=True, text=True).stdout.strip()
    assert out == "Samsung"
    assert tv.vendor(device=tmp_path / "cec0", run=lambda args, **kw: subprocess.run(
        [str(CEC), *args[1:]], env={**os.environ, **env}, **kw)) == "Samsung"


def test_no_adapter_is_quietly_fine(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HEARTH_CEC_DEVICE": str(tmp_path / "none")}
    # (it waits up to 10 s for a slow adapter; don't make the test wait)
    text = CEC.read_text().replace("for _ in $(seq 20)", "for _ in $(seq 1)")
    script = tmp_path / "hearth-cec"
    script.write_text(text)
    script.chmod(0o755)
    assert subprocess.run([str(script), "switch"], env=env).returncode == 0
    assert tv.vendor(device=tmp_path / "none") is None
