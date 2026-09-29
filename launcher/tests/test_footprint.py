"""hearthctl footprint: memory and CPU in use, and by what."""

from pathlib import Path

from hearth import footprint


def fake_proc(tmp_path: Path, ticks: int) -> Path:
    proc = tmp_path / "proc"
    (proc).mkdir(exist_ok=True)
    (proc / "meminfo").write_text("MemTotal:       16000000 kB\nMemFree:  1000000 kB\nMemAvailable:   12000000 kB\n")
    procs = {
        "100": (b"/usr/bin/python3\0-m\0hearth\0", "python3", 50_000, ticks),
        "101": (b"/usr/bin/python3\0-m\0hearth.overlay\0", "python3", 30_000, ticks // 2),
        "200": (b"C:\\Games\\Hades\\Hades.exe\0", "Hades.exe", 900_000, ticks * 10),
        "201": (b"C:\\Games\\Hades\\Hades.exe\0-child\0", "Hades.exe", 100_000, 0),
        "300": (b"", "kworker/0:1", 0, 0),
    }
    for pid, (cmd, comm, pss_kb, t) in procs.items():
        d = proc / pid
        d.mkdir(exist_ok=True)
        (d / "cmdline").write_bytes(cmd)
        (d / "comm").write_text(comm + "\n")
        (d / "stat").write_text(f"{pid} ({comm}) S 1 1 1 0 -1 0 0 0 0 0 {t} 0 0 0 20 0 1 0\n")
        (d / "smaps_rollup").write_text(f"Rss: {pss_kb * 2} kB\nPss: {pss_kb} kB\n")
    return proc


def test_program_names():
    assert footprint.program_name(b"/usr/bin/python3\0-m\0hearth.overlay\0--config\0x\0", "python3") == "hearth.overlay"
    assert footprint.program_name(b"Z:\\x\\steamapps\\common\\Hades\\Hades.exe\0", "wine") == "Hades.exe"
    assert footprint.program_name(b"/usr/bin/pipewire\0", "pipewire") == "pipewire"
    assert footprint.program_name(b"", "kworker/0:1") == "kworker/0:1"


def test_measure_groups_programs_and_counts_hearth(tmp_path):
    proc = fake_proc(tmp_path, 0)

    def advance(seconds):  # the CPU sample: time passes, the processes use some
        fake_proc(tmp_path, 100)

    f = footprint.measure(1.0, proc=proc, sleep=advance)
    assert f.total == 16_000_000 * 1024 and f.used == 4_000_000 * 1024
    assert f.programs[0].name == "Hades.exe" and f.programs[0].processes == 2  # biggest first, grouped
    assert f.programs[0].memory == 1_000_000 * 1024
    h = f.hearth
    assert h.processes == 2 and h.memory == 80_000 * 1024 and h.cpu > 0
    text = footprint.report(f)
    assert "Hearth itself: 78 MB" in text and "Hades.exe ×2" in text and "kworker" not in text
