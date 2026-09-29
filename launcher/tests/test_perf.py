"""The Performance tab: usage, temperatures, and "slowing down"."""

from hearth import perf
from hearth.quickmenu import Context, build_tabs


def fake_system(tmp_path, cpu_temp=55.0, junction=70.0, gpu_busy=40, gpu_mhz=(500, 2600, 1800), cur_cpu=4400000):
    proc, sys = tmp_path / "proc", tmp_path / "sys"
    proc.mkdir()
    (proc / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal:       24000000 kB\nMemAvailable:   15000000 kB\n")
    for n in range(2):
        f = sys / f"devices/system/cpu/cpu{n}/cpufreq"
        f.mkdir(parents=True)
        (f / "scaling_cur_freq").write_text(f"{cur_cpu}\n")
        (f / "cpuinfo_max_freq").write_text("4500000\n")
    k10 = sys / "class/hwmon/hwmon0"
    k10.mkdir(parents=True)
    (k10 / "name").write_text("k10temp\n")
    (k10 / "temp1_input").write_text(f"{int(cpu_temp * 1000)}\n")
    (k10 / "temp1_label").write_text("Tctl\n")
    gpu = sys / "class/hwmon/hwmon1"
    gpu.mkdir(parents=True)
    (gpu / "name").write_text("amdgpu\n")
    for i, (label, t) in enumerate((("edge", junction - 15), ("junction", junction)), 1):
        (gpu / f"temp{i}_input").write_text(f"{int(t * 1000)}\n")
        (gpu / f"temp{i}_label").write_text(label + "\n")
    (gpu / "power1_average").write_text("180000000\n")
    (gpu / "power1_cap").write_text("203000000\n")
    dev = sys / "class/drm/card1/device"
    dev.mkdir(parents=True)
    (dev / "gpu_busy_percent").write_text(f"{gpu_busy}\n")
    lo, hi, cur = gpu_mhz
    (dev / "pp_dpm_sclk").write_text(f"0: {lo}Mhz{' *' if cur == lo else ''}\n1: {cur}Mhz *\n2: {hi}Mhz\n")
    (dev / "mem_info_vram_used").write_text(str(5 * 1024 ** 3))
    (dev / "mem_info_vram_total").write_text(str(12 * 1024 ** 3))
    return proc, sys


def test_reads_usage_temps_and_clocks(tmp_path):
    proc, sys = fake_system(tmp_path)
    m = perf.Monitor(proc, sys)
    first = m.read()
    assert first.cpu_load is None  # needs two samples
    (proc / "stat").write_text("cpu  500 0 100 1200 0 0 0 0 0 0\n")  # 400 more busy, 400 more idle
    r = m.read()
    assert round(r.cpu_load) == 50 and r.cpu_temp == 55 and r.cpu_mhz == 4400 and r.cpu_max_mhz == 4500
    assert r.gpu_load == 40 and r.gpu_hotspot == 70 and r.gpu_temp == 55 and r.gpu_mhz == 1800 and r.gpu_max_mhz == 2600
    assert round(r.gpu_watts) == 180 and round(r.gpu_cap_watts) == 203
    assert r.ram_total == 24000000 * 1024 and r.vram_total == 12 * 1024 ** 3
    assert r.warnings == [] and r.status == "Cool"


def test_hot_gpu_is_flagged(tmp_path):
    r = perf.Monitor(*fake_system(tmp_path, junction=107)).read()
    assert "slowing" in r.warnings[0] and r.status == "Slowing down to cool off"


def test_busy_but_slow_cpu_is_throttling(tmp_path):
    proc, sys = fake_system(tmp_path, cpu_temp=75, cur_cpu=2000000)
    m = perf.Monitor(proc, sys)
    m.read()
    (proc / "stat").write_text("cpu  1000 0 100 820 0 0 0 0 0 0\n")  # ~98% busy
    r = m.read()
    assert any("CPU busy but running slow" in w for w in r.warnings)


def test_no_sensors(tmp_path):
    (tmp_path / "proc").mkdir()
    r = perf.Monitor(tmp_path / "proc", tmp_path / "sys").read()
    assert r.status == "No sensors found" and r.warnings == []


def test_quick_menu_tab(tmp_path):
    from fakes import FakeActions, FakePactl
    from hearth.audio import Audio

    r = perf.Monitor(*fake_system(tmp_path, junction=99)).read()
    audio = Audio(FakePactl())
    ctx = Context(audio, audio.snapshot(), {"foreground": None, "background": {}, "focus": "home"},
                  FakeActions(), perf=r)
    tab = next(t for t in build_tabs(ctx) if t.key == "performance")
    items = {i.key: i for i in tab.items}
    assert items["perf-status"].label == "Warm, but fine"
    assert items["perf-gpu"].alert and "99°C" in items["perf-gpu"].detail and "1800/2600 MHz" in items["perf-gpu"].detail
    assert items["perf-ram"].unit.endswith("of 22.9 GB") and "video 5.0/12.0 GB" in items["perf-ram"].detail
    assert not any(i.selectable for i in tab.items)
