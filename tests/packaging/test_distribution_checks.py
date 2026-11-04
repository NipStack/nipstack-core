"""Offline regressions for archive coverage, installation failure and import isolation."""

import io
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from check_distributions import install_and_smoke, verify_distribution_files
from smoke_installed import assert_installed_location


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    package = tmp_path / "src" / "nipstack_core"
    for name in ("__init__.py", "py.typed", "profiles/actions.py", "resources/example.json"):
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return package


def write_archives(
    dist_dir: Path, wheel_names: set[str], sdist_names: set[str]
) -> tuple[Path, Path]:
    dist_dir.mkdir(exist_ok=True)
    wheel = dist_dir / "nipstack_core-0.1.0-py3-none-any.whl"
    sdist = dist_dir / "nipstack_core-0.1.0.tar.gz"
    with ZipFile(wheel, "w") as archive:
        for name in sorted(wheel_names):
            archive.writestr(name, "")
    with tarfile.open(sdist, "w:gz") as archive:
        for name in sorted(sdist_names):
            archive.addfile(tarfile.TarInfo(name), io.BytesIO())
    return wheel, sdist


@pytest.fixture
def archive_names(package_dir: Path) -> tuple[set[str], set[str]]:
    wheel_names = {
        f"nipstack_core/{path.relative_to(package_dir).as_posix()}"
        for path in package_dir.rglob("*")
        if path.is_file()
    }
    return wheel_names, {f"nipstack_core-0.1.0/src/{name}" for name in wheel_names}


def test_all_source_package_files_are_required_without_module_enumeration(
    tmp_path: Path, package_dir: Path, archive_names: tuple[set[str], set[str]]
) -> None:
    (package_dir / "AGENTS.md").write_text("Instructions", encoding="utf-8")
    cache = package_dir / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-312.pyc").write_bytes(b"cache")
    paths = write_archives(tmp_path / "dist", *archive_names)
    assert verify_distribution_files(tmp_path / "dist", package_dir) == paths


@pytest.mark.parametrize("distribution", ["wheel", "sdist"])
@pytest.mark.parametrize(
    "missing", ["__init__.py", "py.typed", "profiles/actions.py", "resources/example.json"]
)
def test_missing_modules_resources_and_typing_marker_fail(
    tmp_path: Path,
    package_dir: Path,
    archive_names: tuple[set[str], set[str]],
    distribution: str,
    missing: str,
) -> None:
    wheel_names, sdist_names = archive_names
    if distribution == "wheel":
        wheel_names.remove(f"nipstack_core/{missing}")
    else:
        sdist_names.remove(f"nipstack_core-0.1.0/src/nipstack_core/{missing}")
    write_archives(tmp_path / "dist", wheel_names, sdist_names)
    with pytest.raises(AssertionError, match="missing package files"):
        verify_distribution_files(tmp_path / "dist", package_dir)


@pytest.mark.parametrize(
    ("distribution", "forbidden"),
    [
        ("wheel", "nipstack_core/AGENTS.md"),
        ("wheel", "tests/fakes/connector.py"),
        ("sdist", "nipstack_core-0.1.0/tests/fakes/connector.py"),
    ],
)
def test_forbidden_archive_content_fails(
    tmp_path: Path,
    package_dir: Path,
    archive_names: tuple[set[str], set[str]],
    distribution: str,
    forbidden: str,
) -> None:
    names = archive_names[0 if distribution == "wheel" else 1]
    names.add(forbidden)
    write_archives(tmp_path / "dist", *archive_names)
    with pytest.raises(AssertionError, match="must not"):
        verify_distribution_files(tmp_path / "dist", package_dir)


@pytest.mark.parametrize("distribution", ["wheel", "sdist"])
@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_distributions_fail(
    tmp_path: Path,
    package_dir: Path,
    archive_names: tuple[set[str], set[str]],
    distribution: str,
    count: int,
) -> None:
    paths = write_archives(tmp_path / "dist", *archive_names)
    artifact = paths[0 if distribution == "wheel" else 1]
    if count == 0:
        artifact.unlink()
    else:
        artifact.with_name("extra" + "".join(artifact.suffixes)).write_bytes(artifact.read_bytes())
    with pytest.raises(AssertionError, match=f"exactly one {distribution}"):
        verify_distribution_files(tmp_path / "dist", package_dir)


def test_multiple_sdist_roots_fail(
    tmp_path: Path, package_dir: Path, archive_names: tuple[set[str], set[str]]
) -> None:
    archive_names[1].add("other-root/file")
    write_archives(tmp_path / "dist", *archive_names)
    with pytest.raises(AssertionError, match="one root"):
        verify_distribution_files(tmp_path / "dist", package_dir)


def test_installed_module_must_not_come_from_checkout(tmp_path: Path) -> None:
    module = ModuleType("nipstack_core")
    module.__file__ = str(tmp_path / "checkout" / "src" / "nipstack_core" / "__init__.py")
    with pytest.raises(AssertionError, match="outside the isolated environment"):
        assert_installed_location(module, tmp_path / "venv")
    module.__file__ = str(tmp_path / "venv" / "lib" / "nipstack_core" / "__init__.py")
    assert_installed_location(module, tmp_path / "venv")


def test_each_install_uses_fresh_environment_and_isolated_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    smoke = tmp_path / "smoke_installed.py"
    for distribution in ("wheel", "sdist"):
        work = tmp_path / distribution
        work.mkdir()
        artifact = tmp_path / distribution
        install_and_smoke(artifact, work, smoke, "0.1.0")
        python = work / "venv" / "bin" / "python"
        assert run.call_args_list[-3].args == (
            ["uv", "venv", "--python", sys.executable, str(work / "venv")],
        )
        assert run.call_args_list[-2].args == (
            ["uv", "pip", "install", "--python", str(python), "--no-cache", str(artifact)],
        )
        assert run.call_args_list[-1].args == ([str(python), "-I", str(smoke), "0.1.0"],)
        for call in run.call_args_list[-3:]:
            assert call.kwargs == {"cwd": work, "check": True}


@pytest.mark.parametrize("failed_step", [0, 1, 2])
def test_installation_and_smoke_failures_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_step: int
) -> None:
    error = subprocess.CalledProcessError(1, ["synthetic-command"])
    run = Mock(side_effect=[None] * failed_step + [error])
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        install_and_smoke(tmp_path / "artifact", tmp_path, tmp_path / "smoke.py", "0.1.0")
    assert run.call_count == failed_step + 1
