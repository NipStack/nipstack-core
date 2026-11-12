import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[2] / "tools/benchmark_native.py"
HELPERS = runpy.run_path(str(SCRIPT))


@pytest.mark.parametrize("name", HELPERS["CASES"])
def test_benchmark_workloads_match_independent_oracles_and_rejection_codes(name):
    case = HELPERS["_workload"](name)
    prepared = HELPERS["compile_native"](case.body)
    HELPERS["_verify"](case, HELPERS["_invoke"](case, prepared))


def test_cold_compilation_times_the_first_compile_call_after_preparation(monkeypatch):
    measure = HELPERS["_measure"]
    globals_ = measure.__globals__
    original = globals_["compile_native"]
    events = []

    def compile_tracked(body):
        events.append("compile")
        return original(body)

    def wall():
        events.append("wall")
        return len(events)

    def cpu():
        events.append("cpu")
        return len(events)

    monkeypatch.setitem(globals_, "compile_native", compile_tracked)
    monkeypatch.setattr(globals_["time"], "perf_counter_ns", wall)
    monkeypatch.setattr(globals_["time"], "process_time_ns", cpu)
    measure("compile", "cold_compile", 1, 0)
    assert events == ["wall", "cpu", "compile", "cpu", "wall"]


def test_measurement_aborts_on_incorrect_output(monkeypatch):
    measure = HELPERS["_measure"]
    monkeypatch.setitem(measure.__globals__, "parse_native", lambda *args: ())
    with pytest.raises(RuntimeError, match="independent synthetic oracle"):
        measure("flat-100", "timing", 2, 0)


def test_rss_distinguishes_post_exec_peak_from_inherited_launcher_high_water(monkeypatch):
    rss = HELPERS["_rss"]
    monkeypatch.setattr(Path, "read_text", lambda *args: "VmHWM:\t2048 kB\n")
    monkeypatch.setattr(
        rss.__globals__["resource"],
        "getrusage",
        lambda *args: SimpleNamespace(ru_maxrss=65536),
    )
    assert rss() == {"rss_peak_bytes": 2097152, "rusage_maxrss_bytes": 67108864}


def test_benchmark_cli_uses_distinct_cold_and_memory_workers(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            str(SCRIPT),
            "--case",
            "compile",
            "--samples",
            "2",
            "--cold-samples",
            "2",
            "--memory-samples",
            "2",
            "--warmups",
            "0",
        ],
        text=True,
        capture_output=True,
        cwd=tmp_path,
        check=True,
        timeout=60,
    )
    report = json.loads(completed.stdout)
    phases = report["cases"]["compile"]
    pids = []
    for phase in ("cold_compile", "python_memory", "rss"):
        workers = phases[phase]["workers"]
        assert len(workers) == 2
        assert all(len(worker["observations"]) == 1 for worker in workers)
        pids.extend(worker["pid"] for worker in workers)
    assert len(set(pids)) == len(pids)
    assert len(phases["timing"]["workers"][0]["observations"]) == 2
