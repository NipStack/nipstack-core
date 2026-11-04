"""Check built archives, then install and smoke-test each distribution independently."""

import argparse
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def verify_distribution_files(dist_dir: Path, package_dir: Path) -> tuple[Path, Path]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    assert len(wheels) == 1, f"Expected exactly one wheel, got {wheels}"
    assert len(sdists) == 1, f"Expected exactly one sdist, got {sdists}"
    assert package_dir.is_dir(), f"Missing source package: {package_dir}"

    expected = {
        f"nipstack_core/{path.relative_to(package_dir).as_posix()}"
        for path in package_dir.rglob("*")
        if path.is_file()
        and path.name != "AGENTS.md"
        and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    }
    expected.update({"nipstack_core/__init__.py", "nipstack_core/py.typed"})

    with ZipFile(wheels[0]) as archive:
        wheel_names = set(archive.namelist())
    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_names = set(archive.getnames())

    for names in (wheel_names, sdist_names):
        assert not any("fakes" in PurePosixPath(name).parts for name in names), (
            "Test fakes must not be distributed"
        )
    assert not any(PurePosixPath(name).name == "AGENTS.md" for name in wheel_names), (
        "Wheel must not contain AGENTS.md"
    )
    assert expected <= wheel_names, (
        f"Wheel is missing package files: {sorted(expected - wheel_names)}"
    )

    roots = {PurePosixPath(name).parts[0] for name in sdist_names}
    assert len(roots) == 1, "Sdist must have exactly one root directory"
    source_names = {"/".join(PurePosixPath(name).parts[1:]) for name in sdist_names}
    expected_source = {f"src/{name}" for name in expected}
    assert expected_source <= source_names, (
        f"Sdist is missing package files: {sorted(expected_source - source_names)}"
    )
    return wheels[0].resolve(), sdists[0].resolve()


def install_and_smoke(
    artifact: Path, work_dir: Path, smoke_script: Path, expected_version: str
) -> None:
    environment = work_dir / "venv"
    python = environment / "bin" / "python"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(environment)],
        cwd=work_dir,
        check=True,
    )
    # Bypass cached builds so the sdist installation really rebuilds the supplied archive.
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--no-cache", str(artifact)],
        cwd=work_dir,
        check=True,
    )
    subprocess.run(
        [str(python), "-I", str(smoke_script), expected_version],
        cwd=work_dir,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", type=Path, help="Directory with one wheel and one sdist")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    wheel, sdist = verify_distribution_files(args.dist_dir, root / "src" / "nipstack_core")
    with (root / "pyproject.toml").open("rb") as manifest:
        expected_version = tomllib.load(manifest)["project"]["version"]
    assert isinstance(expected_version, str), "Project version must be a string"
    print("Wheel and sdist contents verified", flush=True)

    smoke_script = Path(__file__).resolve().with_name("smoke_installed.py")
    with TemporaryDirectory(prefix="nipstack-distributions-") as temporary:
        for label, artifact in (("wheel", wheel), ("sdist", sdist)):
            work_dir = Path(temporary) / label
            work_dir.mkdir()
            print(f"Installing and testing {label}: {artifact.name}", flush=True)
            install_and_smoke(artifact, work_dir, smoke_script, expected_version)


if __name__ == "__main__":
    main()
