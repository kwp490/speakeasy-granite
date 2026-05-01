"""Tests for build/installer naming consistency.

These tests catch stale names and broken cross-file references that prevent
Build-Installer.ps1 from working.  They parse the build scripts statically
(no execution) and verify that every path, GUID, module name, and process
name agrees with the actual files on disk.
"""

import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# â”€â”€ Helper: read a file as text â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _read(relpath: str) -> str:
    return (_REPO_ROOT / relpath).read_text(encoding="utf-8")


# â”€â”€ Helpers: extract values from Inno Setup (.iss) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _iss_define(text: str, name: str) -> str | None:
    """Return the value of ``#define <name> "value"`` from an .iss file."""
    m = re.search(rf'#define\s+{re.escape(name)}\s+"([^"]+)"', text)
    return m.group(1) if m else None


def _iss_app_id(text: str) -> str | None:
    """Return the raw AppId GUID (without leading ``{{``)."""
    m = re.search(r"AppId=\{\{([^}]+)\}", text)
    return m.group(1) if m else None


class TestBuildInstallerPaths(unittest.TestCase):
    """Build-Installer.ps1 must reference files that actually exist."""

    @classmethod
    def setUpClass(cls):
        cls.build_ps1 = _read("installer/Build-Installer.ps1")

    def test_iss_filename_matches_disk(self):
        """The .iss paths passed to Build-Variant must point to real files."""
        # Build-Installer.ps1 references .iss files via -IssFile parameters
        iss_refs = re.findall(r"-IssFile\s+'([^']+)'", self.build_ps1)
        if not iss_refs:
            # Fallback: old-style direct isccArgs assignment
            m = re.search(r'isccArgs\s*=\s*@\("([^"]+)"\)', self.build_ps1)
            self.assertIsNotNone(m, "Could not find .iss file reference in Build-Installer.ps1")
            iss_refs = [m.group(1)]
        for iss_path in iss_refs:
            iss_path_norm = iss_path.replace("\\", "/")
            self.assertTrue(
                (_REPO_ROOT / iss_path_norm).exists(),
                f"Build-Installer.ps1 references '{iss_path}' but the file does not exist. "
                f"Actual .iss files: {[p.name for p in (_REPO_ROOT / 'installer').glob('*.iss')]}",
            )

    def test_source_hash_directory_exists(self):
        """Get-SourceHash must scan the actual Python package directory."""
        m = re.search(r'Get-ChildItem\s+-Path\s+"([^"]+)".*-Recurse.*\.py', self.build_ps1)
        self.assertIsNotNone(m, "Could not find Get-ChildItem in Get-SourceHash")
        pkg_dir = m.group(1)
        self.assertTrue(
            (_REPO_ROOT / pkg_dir).is_dir(),
            f"Get-SourceHash scans '{pkg_dir}/' but that directory does not exist. "
            f"The Python package directory is 'speakeasy/'.",
        )

    def test_spec_file_referenced_exists(self):
        """The .spec file referenced in Build-Installer.ps1 must exist."""
        m = re.search(r'"([\w.-]+\.spec)"', self.build_ps1)
        self.assertIsNotNone(m, "Could not find .spec reference in Build-Installer.ps1")
        self.assertTrue(
            (_REPO_ROOT / m.group(1)).exists(),
            f"Build-Installer.ps1 references '{m.group(1)}' but it does not exist.",
        )


class TestBuildInstallerReleaseReferences(unittest.TestCase):
    """Build-Installer.ps1 release mode must agree with speakeasy-setup.iss and the package layout."""

    @classmethod
    def setUpClass(cls):
        cls.build_ps1_full = _read("installer/Build-Installer.ps1")
        cls.iss_text = _read("installer/speakeasy-setup.iss")

    def test_registry_guid_matches_iss(self):
        """The uninstall GUID in Build-Installer.ps1 must match AppId in .iss."""
        iss_guid = _iss_app_id(self.iss_text)
        self.assertIsNotNone(iss_guid, "Could not parse AppId from speakeasy-setup.iss")

        # Find all GUIDs in the Build-Installer.ps1 uninstall key lines
        guids = re.findall(
            r"Uninstall\\\{([0-9A-Fa-f-]+)\}_is1", self.build_ps1_full
        )
        self.assertTrue(len(guids) > 0, "No uninstall GUIDs found in Build-Installer.ps1")
        for guid in guids:
            self.assertEqual(
                guid, iss_guid,
                f"Build-Installer.ps1 GUID '{guid}' does not match "
                f"speakeasy-setup.iss AppId '{iss_guid}'",
            )

    def test_module_name_matches_package(self):
        """The 'python -m <module>' invocation must use the real package name."""
        m = re.search(r"python\s+-m\s+([\w.]+)", self.build_ps1_full)
        self.assertIsNotNone(m, "Could not find 'python -m' in Build-Installer.ps1")
        module_name = m.group(1)
        self.assertTrue(
            (_REPO_ROOT / module_name.replace(".", "/")).is_dir(),
            f"Build-Installer.ps1 invokes 'python -m {module_name}' but "
            f"'{module_name.replace('.', '/')}/' does not exist.",
        )

    def test_process_name_matches_exe(self):
        """Get-Process name must match the exe name (without extension)."""
        m = re.search(r"Get-Process\s+-Name\s+'([^']+)'", self.build_ps1_full)
        self.assertIsNotNone(m, "Could not find Get-Process in Build-Installer.ps1")
        process_name = m.group(1)

        exe_name = _iss_define(self.iss_text, "MyAppExeName")
        self.assertIsNotNone(exe_name, "Could not parse MyAppExeName from .iss")
        expected = exe_name.removesuffix(".exe")
        self.assertEqual(
            process_name, expected,
            f"Get-Process name '{process_name}' does not match "
            f"exe name '{exe_name}' (expected '{expected}')",
        )

    def test_installer_glob_matches_iss_output(self):
        """The glob pattern used to find the setup exe must match OutputBaseFilename."""
        output_base = re.search(r"OutputBaseFilename=(.+)", self.iss_text)
        self.assertIsNotNone(output_base, "Could not parse OutputBaseFilename from .iss")
        # OutputBaseFilename contains {#MyAppVersion} which resolves to the version
        # Build-Installer.ps1 uses a wildcard like SpeakEasy-AI-Granite-Setup-*.exe
        iss_base = output_base.group(1).strip()
        # Replace InnoSetup preprocessor tokens with regex wildcards
        iss_pattern = re.sub(r"\{#\w+\}", ".*", iss_base)

        # Build-Installer.ps1 may use either a direct glob string or a variable
        # expression for the installer pattern.
        m = re.search(r'Get-ChildItem\s+"([^"]+Setup[^"]*\.exe)"', self.build_ps1_full)
        if m is None:
            # Variant-aware: look for the glob pattern in a variable assignment
            m = re.search(r"'(SpeakEasy-AI-Granite-Setup-\*\.exe)'", self.build_ps1_full)
        self.assertIsNotNone(m, "Could not find installer glob in Build-Installer.ps1")
        # Convert PowerShell glob to comparable form (replace * with .*)
        ps_pattern = m.group(1).replace("\\", "/").split("/")[-1].replace("*", ".*")

        # Both patterns must be able to match the same filenames
        test_filename = re.sub(r"\.\*", "0.1.0", iss_pattern) + ".exe"
        self.assertRegex(
            test_filename,
            ps_pattern,
            f"Build-Installer.ps1 glob '{m.group(1)}' would not match "
            f"Inno Setup output '{iss_base}'",
        )


class TestNoStaleProjectNames(unittest.TestCase):
    """No build/installer file should reference the old CV2T / QwenVoiceToText names."""

    _STALE_PATTERNS = re.compile(r"CV2T|QwenVoiceToText|Qwen2-Audio", re.IGNORECASE)

    _FILES_TO_CHECK = [
        "installer/Build-Installer.ps1",
        "installer/speakeasy-setup.iss",
        "speakeasy.spec",
        "pyproject.toml",
        "installer/Install-SpeakEasy-Source.ps1",
    ]

    def test_no_stale_names_in_build_files(self):
        for relpath in self._FILES_TO_CHECK:
            path = _REPO_ROOT / relpath
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            matches = self._STALE_PATTERNS.findall(text)
            self.assertEqual(
                matches,
                [],
                f"{relpath} contains stale project name(s): {matches}",
            )

    def test_no_stale_workspace_files(self):
        """No .code-workspace file in installer/ should have old project names."""
        for ws_file in (_REPO_ROOT / "installer").glob("*.code-workspace"):
            self.assertNotRegex(
                ws_file.name,
                self._STALE_PATTERNS,
                f"Workspace file '{ws_file.name}' contains a stale project name in its filename",
            )


class TestCrossFileVersionConsistency(unittest.TestCase):
    """Version strings must agree across pyproject.toml and speakeasy-setup.iss."""

    def test_versions_match(self):
        pyproject = _read("pyproject.toml")
        m_py = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        self.assertIsNotNone(m_py, "Could not parse version from pyproject.toml")

        iss_text = _read("installer/speakeasy-setup.iss")
        m_iss = _iss_define(iss_text, "MyAppVersion")
        self.assertIsNotNone(m_iss, "Could not parse MyAppVersion from .iss")

        self.assertEqual(
            m_py.group(1), m_iss,
            f"pyproject.toml version '{m_py.group(1)}' != .iss version '{m_iss}'",
        )


class TestTorchTorchaudioCompatibility(unittest.TestCase):
    """torch and torchaudio must be version-compatible and from the same index."""

    def test_torchaudio_uses_same_index_as_torch(self):
        """Both torch and torchaudio must be sourced from the same explicit index."""
        pyproject = _read("pyproject.toml")
        torch_src = re.search(
            r'^\[tool\.uv\.sources\].*?^torch\s*=\s*\{[^}]*index\s*=\s*"([^"]+)"',
            pyproject, re.MULTILINE | re.DOTALL,
        )
        torchaudio_src = re.search(
            r'^\[tool\.uv\.sources\].*?^torchaudio\s*=\s*\{[^}]*index\s*=\s*"([^"]+)"',
            pyproject, re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(
            torch_src,
            "pyproject.toml [tool.uv.sources] must pin torch to an explicit index",
        )
        self.assertIsNotNone(
            torchaudio_src,
            "pyproject.toml [tool.uv.sources] must pin torchaudio to an explicit index "
            "(mismatched builds cause WinError 127 / 0xc0000139)",
        )
        self.assertEqual(
            torch_src.group(1), torchaudio_src.group(1),
            f"torch index '{torch_src.group(1)}' != torchaudio index "
            f"'{torchaudio_src.group(1)}'. Both must use the same CUDA wheel index.",
        )

    def test_installed_torch_torchaudio_major_versions_match(self):
        """Installed torch and torchaudio must share the same major.minor version."""
        import torch
        try:
            import torchaudio
        except OSError:
            self.fail(
                "torchaudio failed to import (likely DLL mismatch with torch). "
                "Reinstall with: uv sync"
            )

        # Strip build metadata like +cu128
        torch_ver = torch.__version__.split("+")[0]
        ta_ver = torchaudio.__version__.split("+")[0]

        torch_major = torch_ver.split(".")[:2]
        ta_major = ta_ver.split(".")[:2]
        self.assertEqual(
            torch_major, ta_major,
            f"torch {torch.__version__} and torchaudio {torchaudio.__version__} "
            f"have mismatched major versions â€” this causes DLL load failures. "
            f"Pin both to the same index in pyproject.toml [tool.uv.sources].",
        )

    def test_installed_torch_torchaudio_build_tags_match(self):
        """Both packages must have the same build tag (e.g. +cu128 or both CPU)."""
        import torch
        try:
            import torchaudio
        except OSError:
            self.fail("torchaudio failed to import (DLL mismatch)")

        torch_tag = torch.__version__.partition("+")[2]  # e.g. "cu128" or ""
        ta_tag = torchaudio.__version__.partition("+")[2]
        self.assertEqual(
            torch_tag, ta_tag,
            f"torch build tag '+{torch_tag}' != torchaudio build tag '+{ta_tag}'. "
            f"Mixing CUDA/CPU builds causes WinError 127.",
        )


class TestInstallerHandlesModelDownload(unittest.TestCase):
    """speakeasy-setup.iss must handle the Granite model and bundle the setup script."""

    @classmethod
    def setUpClass(cls):
        cls.iss_text = _read("installer/speakeasy-setup.iss")

    def test_iss_downloads_granite(self):
        """The ISS script must download the Granite model via download-model."""
        self.assertIsNotNone(
            re.search(r"download-model", self.iss_text),
            "speakeasy-setup.iss must contain a download-model invocation.",
        )

    def test_iss_bundles_granite_setup_script(self):
        """The ISS [Files] section must include granite-model-setup.ps1."""
        self.assertIsNotNone(
            re.search(r'granite-model-setup\.ps1', self.iss_text),
            "speakeasy-setup.iss must reference granite-model-setup.ps1 in the [Files] section.",
        )

    def test_exit_code_constants_match_python(self):
        """The exit code comment in .iss must match the Python constants."""
        from speakeasy.model_downloader import EXIT_AUTH_REQUIRED, EXIT_FAILURE, EXIT_SUCCESS
        self.assertIn(
            f"{EXIT_SUCCESS} = success", self.iss_text,
            "ISS exit code comment for success doesn't match Python EXIT_SUCCESS",
        )
        self.assertIn(
            f"{EXIT_FAILURE} = failure", self.iss_text,
            "ISS exit code comment for failure doesn't match Python EXIT_FAILURE",
        )
        self.assertIn(
            f"{EXIT_AUTH_REQUIRED} = auth required", self.iss_text,
            "ISS exit code comment for auth required doesn't match Python EXIT_AUTH_REQUIRED",
        )


class TestReadmeLinks(unittest.TestCase):
    """README.md download links must use the correct GitHub repo slug and current version."""

    _REPO_SLUG = "kwp490/speakeasy-ai"

    @classmethod
    def setUpClass(cls):
        cls.readme = _read("README.md")
        pyproject = _read("pyproject.toml")
        m = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert m, "Could not parse version from pyproject.toml"
        cls.version = m.group(1)

    def test_no_wrong_repo_slug_in_links(self):
        """No github.com URL in README should use a repo name other than kwp490/speakeasy-ai."""
        wrong = re.findall(
            r"https://github\.com/kwp490/(?!speakeasy-ai(?:\.git)?[/\s)\]])([\w.-]+)",
            self.readme,
        )
        self.assertEqual(
            wrong, [],
            f"README contains GitHub URLs with wrong repo name(s): {wrong}. "
            f"Expected repo slug: '{self._REPO_SLUG}'",
        )

    def test_download_links_use_current_version(self):
        """Installer download links in README must match the current package version."""
        links = re.findall(
            r"https://github\.com/[^/]+/[^/]+/releases/download/v([^/]+)/",
            self.readme,
        )
        for ver in links:
            self.assertEqual(
                ver, self.version,
                f"README download link uses version '{ver}' but pyproject.toml "
                f"is at version '{self.version}'. Update the README links.",
            )


if __name__ == "__main__":
    unittest.main()


