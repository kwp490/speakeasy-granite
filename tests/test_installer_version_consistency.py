"""Version-injection plumbing tests (Phase 7, §14.2).

These static checks guard the single-source-of-truth versioning wiring:

- ``speakeasy/__init__.py`` ``__version__`` is the only literal version.
- ``pyproject.toml`` derives the version dynamically via hatch from that file.
- Both ``.iss`` files keep a ``#define MyAppVersion`` *fallback* guarded by
  ``#ifndef`` so ``Build-Installer.ps1`` can override it with
  ``/DMyAppVersion=<__version__>``.
- ``Build-Installer.ps1`` actually reads ``__version__`` and injects it.

They run without Qt, torch, or a real build.
"""

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    return (_REPO_ROOT / relpath).read_text(encoding="utf-8")


def _package_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', _read("speakeasy/__init__.py"))
    assert m, "Could not parse __version__ from speakeasy/__init__.py"
    return m.group(1)


class TestPyprojectDynamicVersion(unittest.TestCase):
    def setUp(self):
        self.pyproject = _read("pyproject.toml")

    def test_declares_dynamic_version(self):
        self.assertIn(
            'dynamic = ["version"]', self.pyproject,
            "pyproject.toml [project] must declare dynamic = [\"version\"]",
        )

    def test_no_literal_version(self):
        self.assertNotRegex(
            self.pyproject, r'(?m)^version\s*=\s*"',
            "pyproject.toml must not carry a literal version; it is dynamic",
        )

    def test_hatch_version_points_at_init(self):
        self.assertRegex(
            self.pyproject,
            r'\[tool\.hatch\.version\]\s*\npath\s*=\s*"speakeasy/__init__\.py"',
            "pyproject.toml must source the dynamic version from speakeasy/__init__.py",
        )


class TestIssVersionFallback(unittest.TestCase):
    _ISS_FILES = (
        "installer/speakeasy-setup.iss",
        "installer/speakeasy-cpu-setup.iss",
    )

    def test_fallback_is_guarded_by_ifndef(self):
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            with self.subTest(iss=relpath):
                # The #define must be inside an #ifndef MyAppVersion guard so an
                # injected /DMyAppVersion wins over the literal fallback.
                self.assertRegex(
                    text,
                    r"#ifndef\s+MyAppVersion\s*\n\s*#define\s+MyAppVersion\s+\"[^\"]+\"\s*\n\s*#endif",
                    f"{relpath} must guard the MyAppVersion fallback with #ifndef/#endif",
                )

    def test_fallback_matches_package_version(self):
        version = _package_version()
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
            with self.subTest(iss=relpath):
                self.assertIsNotNone(m, f"Could not parse MyAppVersion fallback in {relpath}")
                assert m is not None
                self.assertEqual(
                    m.group(1), version,
                    f"{relpath} fallback '{m.group(1)}' != __version__ '{version}'",
                )


class TestBuildInstallerInjectsVersion(unittest.TestCase):
    def setUp(self):
        self.build_ps1 = _read("installer/Build-Installer.ps1")

    def test_reads_version_from_init(self):
        self.assertIn(
            r"__version__\s*=\s*", self.build_ps1,
            "Build-Installer.ps1 must parse __version__ via regex",
        )
        self.assertIn(
            "speakeasy\\__init__.py", self.build_ps1,
            "Build-Installer.ps1 must read the version from speakeasy/__init__.py",
        )

    def test_injects_define_into_iscc(self):
        self.assertIn(
            "/DMyAppVersion=$script:AppVersion", self.build_ps1,
            "Build-Installer.ps1 must pass /DMyAppVersion=<version> to iscc",
        )


if __name__ == "__main__":
    unittest.main()
