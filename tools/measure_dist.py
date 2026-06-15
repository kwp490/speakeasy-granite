"""SpeakEasy AI — packaging & dependency size inventory (Phase 0 tooling).

Two measurements feed the baseline document:

* ``--dist``  — walk a PyInstaller onedir build (``dist/speakeasy/_internal``
  by default), report total size and the top-N largest files.  This exposes
  whether ``nvidia-*`` CUDA wheels are double-shipped alongside torch's bundled
  DLLs (see §7.2 of the re-architecture plan).
* ``--deps``  — walk the active environment's ``site-packages`` and report the
  installed on-disk size of each top-level distribution, so the dependency-cut
  phases (librosa→soxr, accelerate, torchaudio) can be judged against real
  numbers.

Both default to running together and print a Markdown table plus JSON.

Usage::

    python tools/measure_dist.py --deps --top 30
    python tools/measure_dist.py --dist dist/speakeasy/_internal --output dist.json
"""

from __future__ import annotations

import argparse
import json
import sys
import sysconfig
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DIST = _REPO_ROOT / "dist" / "speakeasy" / "_internal"


def _dir_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def measure_dist(dist_dir: Path, top: int) -> dict:
    if not dist_dir.is_dir():
        return {"dist_dir": str(dist_dir), "available": False, "files": [], "total_bytes": 0}

    files: list[tuple[int, str]] = []
    total = 0
    for child in dist_dir.rglob("*"):
        if child.is_file():
            try:
                size = child.stat().st_size
            except OSError:
                continue
            total += size
            files.append((size, str(child.relative_to(dist_dir)).replace("\\", "/")))

    files.sort(reverse=True)
    return {
        "dist_dir": str(dist_dir),
        "available": True,
        "total_bytes": total,
        "files": [{"path": p, "bytes": s} for s, p in files[:top]],
    }


def measure_deps(top: int) -> dict:
    site = Path(sysconfig.get_paths()["purelib"])
    if not site.is_dir():
        return {"site_packages": str(site), "available": False, "packages": []}

    sizes: dict[str, int] = {}
    for entry in site.iterdir():
        name = entry.name
        if name.endswith((".dist-info", ".egg-info", ".pth", "__pycache__")):
            continue
        try:
            size = _dir_size(entry) if entry.is_dir() else entry.stat().st_size
        except OSError:
            continue
        # Group by top-level import name (strips e.g. "torch" vs "torchgen").
        sizes[name] = sizes.get(name, 0) + size

    ordered = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "site_packages": str(site),
        "available": True,
        "total_bytes": sum(sizes.values()),
        "packages": [{"name": n, "bytes": b} for n, b in ordered[:top]],
    }


def _mb(num: int) -> str:
    return f"{num / (1024 * 1024):.1f} MB"


def _print_markdown(dist: Optional[dict], deps: Optional[dict]) -> None:
    if deps is not None and deps.get("available"):
        print(f"\n### Installed packages — {sys.executable}")
        print(f"Total site-packages: **{_mb(deps['total_bytes'])}**\n")
        print("| Package | Size |")
        print("| --- | --- |")
        for pkg in deps["packages"]:
            print(f"| {pkg['name']} | {_mb(pkg['bytes'])} |")
    elif deps is not None:
        print("\n### Installed packages — site-packages not found")

    if dist is not None and dist.get("available"):
        print(f"\n### Frozen onedir — {dist['dist_dir']}")
        print(f"Total: **{_mb(dist['total_bytes'])}**\n")
        print("| File | Size |")
        print("| --- | --- |")
        for f in dist["files"]:
            print(f"| {f['path']} | {_mb(f['bytes'])} |")
    elif dist is not None:
        print(f"\n### Frozen onedir — not built yet ({dist['dist_dir']})")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dist + dependency size inventory")
    parser.add_argument("--dist", nargs="?", const=str(_DEFAULT_DIST), default=None,
                        help="Measure a PyInstaller onedir (default dist/speakeasy/_internal).")
    parser.add_argument("--deps", action="store_true", help="Measure installed site-packages.")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    # Default: run both.
    run_dist = args.dist is not None or not args.deps
    run_deps = args.deps or args.dist is None

    dist_result = measure_dist(Path(args.dist or _DEFAULT_DIST), args.top) if run_dist else None
    deps_result = measure_deps(args.top) if run_deps else None

    _print_markdown(dist_result, deps_result)

    payload = {"dist": dist_result, "deps": deps_result}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
