"""Offline Native qualification measurements; Linux RSS is reported in bytes.

Run with the project's Python environment. Workers run sequentially in fresh
interpreters; startup, imports, input generation and verification are not timed.
No performance threshold, cache purge or host-wide setting is applied.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from nipstack_core.contracts.json_data import JSONValue
from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import (
    CompiledNativeTemplate,
    NativeError,
    NativeErrorCode,
    NativeLimits,
)
from nipstack_core.parsers.native.runtime import parse_native

CASES = (
    "compile",
    "flat-100",
    "flat-1000",
    "flat-10000",
    "hierarchy-100",
    "hierarchy-1000",
    "hierarchy-10000",
    "split-5000",
    "expand-4999",
    "map-5000",
    "pipeline-4999",
    "reject-items",
    "reject-blocks",
    "reject-malformed",
    "reject-ambiguous",
)
Phase = Literal["cold_compile", "timing", "python_memory", "rss", "retention"]
Result = CompiledNativeTemplate | JSONValue | tuple[NativeErrorCode, int | None]


@dataclass(frozen=True)
class Workload:
    body: bytes
    text: str
    expected: JSONValue
    selected_blocks: int
    transformed_items: int = 0
    error: tuple[NativeErrorCode, int | None] | None = None


def _hierarchy(blocks: int) -> Workload:
    body = (
        "@record\nparent {{ id }}\n  owner {{ owner }}\n@record items\n"
        "  item {{ value | INT | to_int }}\n  item text {{ label }}\n  ready state\n"
        "    note {{ note | phrase | required }}\n@end\n@end"
    )
    lines: list[str] = []
    expected: list[JSONValue] = []
    for parent in range(blocks // 10):
        lines.extend((f"parent {parent}", "  owner synthetic"))
        children: list[JSONValue] = []
        for child in range(9):
            if child % 3 == 0:
                lines.append(f"  item {child}")
                fields: dict[str, JSONValue] = {"value": child}
            elif child % 3 == 1:
                lines.append(f"  item text label{child}")
                fields = {"label": f"label{child}"}
            else:
                lines.append("  ready state")
                fields = {}
            lines.append("    note payload")
            fields["note"] = "payload"
            children.append(fields)
        expected.append({"id": str(parent), "owner": "synthetic", "items": children})
    return Workload(body.encode(), "\n".join(lines), expected, blocks)


def _workload(name: str) -> Workload:
    if name == "compile":
        return _hierarchy(100)
    if name.startswith("hierarchy-"):
        return _hierarchy(int(name.split("-")[1]))
    if name.startswith("flat-") or name in ("reject-blocks", "reject-malformed"):
        count = int(name.split("-")[1]) if name.startswith("flat-") else 1000
        if name == "reject-blocks":
            count = 10_001
        text = "\n".join(f"item {index}" for index in range(count))
        expected: list[JSONValue] = [{"id": str(index)} for index in range(count)]
        error: tuple[NativeErrorCode, int | None] | None = None
        if name == "reject-blocks":
            error = ("RESOURCE_LIMIT", None)
        elif name == "reject-malformed":
            text += "\nitem"
            error = ("MALFORMED_LINE", count + 1)
        return Workload(b"@record\nitem {{ id }}\n@end", text, expected, count, error=error)
    if name == "reject-ambiguous":
        body = (
            "@record\nparent {{ id }}\n@record items\n"
            "  item {{ value | phrase }}\n  item literal {{ label }}\n@end\n@end"
        )
        text = "\n".join(f"parent {index}\n  item value" for index in range(500))
        text += "\n  item literal X"
        return Workload(body.encode(), text, None, 1000, error=("AMBIGUOUS_MATCH", 1001))
    if name not in ("split-5000", "expand-4999", "map-5000", "pipeline-4999", "reject-items"):
        raise ValueError(f"Unknown workload: {name}")
    if name in ("split-5000", "map-5000"):
        modifier = 'split(",")' + (" | map_int" if name == "map-5000" else "")
        text = "value " + ",".join("1" for _ in range(5000))
        numbers: JSONValue = [1 if name == "map-5000" else "1" for _ in range(5000)]
        items = 10_000 if name == "map-5000" else 5000
    else:
        modifier = 'split(",") | expand_ranges("-")'
        if name != "expand-4999":
            modifier += " | map_int"
        count = 5000 if name == "reject-items" else 4999
        text = f"value 0-{count - 1}"
        numbers = [str(index) if name == "expand-4999" else index for index in range(count)]
        items = 1 + count * (1 if name == "expand-4999" else 2)
    body = f"@section\nRoot\n  value {{{{ numbers | {modifier} }}}}\n@end"
    return Workload(
        body.encode(),
        "Root\n  " + text,
        {"numbers": numbers},
        1,
        items,
        ("RESOURCE_LIMIT", None) if name == "reject-items" else None,
    )


def _plain(value: JSONValue) -> JSONValue:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


def _canonical(value: JSONValue) -> str:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _invoke(case: Workload, prepared: CompiledNativeTemplate | None) -> Result:
    if prepared is None:
        return compile_native(case.body)
    try:
        return parse_native(prepared, case.text)
    except NativeError as error:
        # Do not retain exceptions or their tracebacks between observations.
        return error.code, error.line


def _verify(case: Workload, result: Result) -> None:
    if isinstance(result, CompiledNativeTemplate):
        result = parse_native(result, case.text)
    if case.error is not None:
        if result != case.error:
            raise RuntimeError(f"Expected rejection {case.error}, not {result!r}")
    elif _canonical(result) != _canonical(case.expected):
        raise RuntimeError("Benchmark result differs from the independent synthetic oracle.")


def _describe(case: Workload, compiled: CompiledNativeTemplate) -> dict[str, JSONValue]:
    blocks = (compiled.root, *compiled.root.children)
    patterns = [pattern for block in blocks for pattern in (*block.headers, *block.body)]
    return {
        "template_sha256": hashlib.sha256(case.body).hexdigest(),
        "input_sha256": hashlib.sha256(case.text.encode()).hexdigest(),
        "expected_sha256": hashlib.sha256(_canonical(case.expected).encode()).hexdigest(),
        "template_bytes": len(case.body),
        "input_bytes": len(case.text.encode()),
        "lines": len(case.text.splitlines()),
        "max_line_characters": max(map(len, case.text.splitlines()), default=0),
        "patterns": len(patterns),
        "captures": sum(len(pattern.captures) for pattern in patterns),
        "selected_blocks": case.selected_blocks,
        "transformed_items": case.transformed_items,
        "counts_note": "Required/attempted totals; rejection can precede full emission.",
        "expected_error": list(case.error) if case.error is not None else None,
    }


def _rss() -> dict[str, JSONValue]:
    # ru_maxrss can retain the launcher's pre-exec high-water on Linux.
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            _, size, unit = line.split()
            if unit != "kB":
                raise RuntimeError("Unexpected Linux VmHWM unit.")
            return {
                "rss_peak_bytes": int(size) * 1024,
                "rusage_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            }
    raise RuntimeError("Linux did not expose the worker's post-exec RSS high-water.")


def _measure(name: str, phase: Phase, samples: int, warmups: int) -> dict[str, JSONValue]:
    case = _workload(name)
    prepared = None if name == "compile" else compile_native(case.body)
    observations: list[JSONValue] = []
    if phase in ("timing", "retention"):
        for _ in range(warmups):
            result = _invoke(case, prepared)
            _verify(case, result)
            del result
    if phase in ("python_memory", "retention"):
        gc.collect()
        tracemalloc.start()
    description: dict[str, JSONValue] | None = None
    for iteration in range(1, samples + 1):
        if phase in ("timing", "cold_compile"):
            wall = time.perf_counter_ns()
            cpu = time.process_time_ns()
            result = _invoke(case, prepared)
            cpu = time.process_time_ns() - cpu
            wall = time.perf_counter_ns() - wall
            observation: dict[str, JSONValue] = {"elapsed_ns": wall, "cpu_ns": cpu}
        else:
            result = _invoke(case, prepared)
            if phase == "python_memory":
                current, peak = tracemalloc.get_traced_memory()
                observation = {"python_current_bytes": current, "python_peak_bytes": peak}
                tracemalloc.stop()
            else:
                observation = _rss()
        _verify(case, result)
        if description is None and phase != "retention":
            compiled = result if isinstance(result, CompiledNativeTemplate) else prepared
            assert compiled is not None
            description = _describe(case, compiled)
        del result
        if phase == "retention":
            gc.collect()
            if iteration == 1 or iteration % 5 == 0 or iteration == samples:
                current, peak = tracemalloc.get_traced_memory()
                observation.update(
                    iteration=iteration, python_current_bytes=current, python_peak_bytes=peak
                )
                observations.append(observation)
        else:
            observations.append(observation)
    if phase == "retention":
        tracemalloc.stop()
        assert prepared is not None
        description = _describe(case, prepared)
    return {
        "pid": os.getpid(),
        "phase": phase,
        "workload": description,
        "observations": observations,
    }


def _source(root: Path) -> dict[str, JSONValue]:
    def git(*arguments: str) -> bytes:
        return subprocess.check_output(["git", "--no-pager", *arguments], cwd=root)

    patch = git("diff", "--binary", "HEAD")
    for name in sorted(git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")):
        if not name:
            continue
        completed = subprocess.run(
            [
                "git",
                "--no-pager",
                "diff",
                "--no-index",
                "--binary",
                "--",
                "/dev/null",
                os.fsdecode(name),
            ],
            cwd=root,
            capture_output=True,
        )
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.decode())
        patch += completed.stdout
    return {
        "head_sha": git("rev-parse", "HEAD").decode().strip(),
        "base_main_sha": git("merge-base", "HEAD", "origin/main").decode().strip(),
        "branch": git("branch", "--show-current").decode().strip(),
        "full_local_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "status": git("status", "--short").decode(),
    }


def _environment(note: str) -> dict[str, JSONValue]:
    cpu_info = Path("/proc/cpuinfo").read_text()
    model = next(
        line.split(":", 1)[1].strip()
        for line in cpu_info.splitlines()
        if line.startswith("model name")
    )
    constraints = {
        str(path): path.read_text().strip() if path.is_file() else "not exposed at this path"
        for path in (Path("/sys/fs/cgroup/cpu.max"), Path("/sys/fs/cgroup/memory.max"))
    }
    return {
        "python": sys.version,
        "executable": sys.executable,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "libc": list(platform.libc_ver()),
        "cpu_model": model,
        "cpu_count": os.cpu_count(),
        "cpu_affinity": tuple(sorted(os.sched_getaffinity(0))),
        "load_average": list(os.getloadavg()),
        "constraints": constraints,
        "rlimit_as": list(resource.getrlimit(resource.RLIMIT_AS)),
        "gc_enabled": gc.isenabled(),
        "clock_resolution_seconds": {
            name: time.get_clock_info(name).resolution for name in ("perf_counter", "process_time")
        },
        "dependencies": {
            distribution.metadata["Name"]: distribution.version
            for distribution in importlib.metadata.distributions()
        },
        "environment_note": note,
    }


def _worker(name: str, phase: Phase, samples: int, warmups: int) -> dict[str, JSONValue]:
    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            str(Path(__file__).resolve()),
            "--worker",
            phase,
            "--case",
            name,
            "--samples",
            str(samples),
            "--warmups",
            str(warmups),
        ],
        text=True,
        capture_output=True,
        check=True,
        timeout=600,
        env=os.environ | {"PYTHONHASHSEED": "0"},
    )
    if completed.stderr:
        raise RuntimeError(f"Unexpected benchmark worker stderr: {completed.stderr}")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise RuntimeError("Benchmark worker returned an invalid report.")
    return result


def _summary(workers: list[dict[str, JSONValue]]) -> dict[str, JSONValue]:
    metrics: dict[str, list[int | float]] = {}
    for worker in workers:
        observations = worker["observations"]
        assert isinstance(observations, list)
        for observation in observations:
            assert isinstance(observation, Mapping)
            for metric, value in observation.items():
                assert isinstance(value, (int, float))
                metrics.setdefault(metric, []).append(value)
    summary: dict[str, JSONValue] = {}
    for metric, values in metrics.items():
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        summary[metric] = {
            "median": statistics.median(values),
            "iqr": quartiles[2] - quartiles[0],
            "pstdev": statistics.pstdev(values),
            "min": min(values),
            "max": max(values),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, action="append", dest="cases")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--cold-samples", type=int, default=5)
    parser.add_argument("--memory-samples", type=int, default=3)
    parser.add_argument(
        "--environment-note", default="Unspecified; do not assume dedicated resources."
    )
    parser.add_argument(
        "--worker",
        choices=("cold_compile", "timing", "python_memory", "rss", "retention"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This RSS protocol requires Linux; other platforms are not qualified.")
    if args.worker:
        if not args.cases or len(args.cases) != 1 or args.samples < 1:
            parser.error("Workers require exactly one case and at least one sample.")
        if args.worker in ("cold_compile", "python_memory", "rss") and args.samples != 1:
            parser.error("Cold compilation and memory observations require one fresh worker each.")
        if args.worker == "cold_compile" and args.cases != ["compile"]:
            parser.error("Cold compilation requires the compile case.")
        print(json.dumps(_measure(args.cases[0], args.worker, args.samples, args.warmups)))
        return
    if min(args.samples, args.cold_samples, args.memory_samples) < 2 or args.warmups < 0:
        parser.error("Use at least two samples per campaign and nonnegative warmups.")
    root = Path(__file__).resolve().parents[1]
    source = _source(root)
    report: dict[str, JSONValue] = {
        "started_at": datetime.now(UTC).isoformat(),
        "command": [sys.executable, *sys.argv],
        "source": source,
        "environment": _environment(args.environment_note),
        "protocol": {
            "warmups": args.warmups,
            "samples": args.samples,
            "cold_samples": args.cold_samples,
            "memory_samples": args.memory_samples,
            "batch_size": 1,
            "hash_seed": "0",
            "limits": {
                field.name: getattr(NativeLimits(), field.name) for field in fields(NativeLimits)
            },
            "memory_scope": "VmHWM measures post-exec process RSS peak; ru_maxrss is also recorded and can retain launcher high-water. Includes interpreter, libraries, case/oracle preparation and compilation; Python tracing starts after preparation. Not Native-only memory.",
            "timing_scope": "Operation call only; no startup/imports/generation/verification or returned-output cleanup. GC remains enabled; caches are not purged.",
            "worker_timeout_seconds": 600,
        },
    }
    cases: dict[str, JSONValue] = {}
    for name in args.cases or CASES:
        print(f"Measuring {name}", file=sys.stderr, flush=True)
        phases: dict[str, JSONValue] = {}
        for phase in ("timing", "python_memory", "rss"):
            workers = (
                [_worker(name, phase, args.samples, args.warmups)]
                if phase == "timing"
                else [_worker(name, phase, 1, 0) for _ in range(args.memory_samples)]
            )
            phases[phase] = {"workers": tuple(workers), "summary": _summary(workers)}
        if name == "compile":
            workers = [_worker(name, "cold_compile", 1, 0) for _ in range(args.cold_samples)]
            phases["cold_compile"] = {"workers": tuple(workers), "summary": _summary(workers)}
        if name == "hierarchy-1000":
            phases["retention"] = _worker(name, "retention", args.samples, args.warmups)
        cases[name] = phases
    report["cases"] = cases
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["final_load_average"] = list(os.getloadavg())
    if source != _source(root):
        raise RuntimeError("Local sources changed during the campaign; discard these measurements.")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
