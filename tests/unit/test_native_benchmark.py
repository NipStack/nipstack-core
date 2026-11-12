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


@pytest.fixture
def shallow_checkout(tmp_path):
    source = tmp_path / "source"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(source)], check=True, capture_output=True
    )
    script = source / "tools/benchmark_native.py"
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    subprocess.run(["git", "add", "tools/benchmark_native.py"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Synthetic baseline",
        ],
        cwd=source,
        check=True,
        capture_output=True,
    )
    baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    subprocess.run(["git", "branch", "qualification"], cwd=source, check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(
        [
            "git",
            "clone",
            "--depth=1",
            "--single-branch",
            "--branch=qualification",
            source.as_uri(),
            str(checkout),
        ],
        check=True,
        capture_output=True,
    )
    return checkout, baseline


@pytest.mark.parametrize("detached", [False, True])
def test_benchmark_cli_uses_distinct_cold_and_memory_workers(tmp_path, shallow_checkout, detached):
    checkout, baseline = shallow_checkout
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "--is-shallow-repository"], cwd=checkout, text=True
        ).strip()
        == "true"
    )
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "refs/remotes/origin/main"],
            cwd=checkout,
            capture_output=True,
        ).returncode
        != 0
    )
    if detached:
        subprocess.run(
            ["git", "checkout", "--detach"], cwd=checkout, check=True, capture_output=True
        )
    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            str(checkout / "tools/benchmark_native.py"),
            "--base-main-sha",
            baseline,
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
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["source"]["base_main_sha"] == baseline
    assert report["source"]["head_sha"] == baseline
    assert report["source"]["branch"] == ("" if detached else "qualification")
    phases = report["cases"]["compile"]
    pids = []
    for phase in ("cold_compile", "python_memory", "rss"):
        workers = phases[phase]["workers"]
        assert len(workers) == 2
        assert all(len(worker["observations"]) == 1 for worker in workers)
        pids.extend(worker["pid"] for worker in workers)
    assert len(set(pids)) == len(pids)
    assert len(phases["timing"]["workers"][0]["observations"]) == 2


def test_missing_baseline_is_explicit_and_never_substituted_with_head(shallow_checkout):
    checkout, baseline = shallow_checkout
    with pytest.raises(RuntimeError, match="--base-main-sha"):
        HELPERS["_source"](checkout)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", baseline], cwd=checkout, check=True
    )
    assert HELPERS["_source"](checkout)["base_main_sha"] == baseline


def test_explicit_baseline_must_be_a_full_available_commit_sha(shallow_checkout):
    checkout, _ = shallow_checkout
    with pytest.raises(ValueError, match="complete commit SHA"):
        HELPERS["_source"](checkout, base_main_sha="HEAD")
    with pytest.raises(RuntimeError, match="--base-main-sha"):
        HELPERS["_source"](checkout, base_main_sha="0" * 40)
