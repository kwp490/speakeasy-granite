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

# Helper: read a file as text

def _read(relpath: str) -> str:
    return (_REPO_ROOT / relpath).read_text(encoding="utf-8")


# Helpers: extract values from Inno Setup (.iss)

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
            assert m is not None
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
        assert m is not None
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
        assert m is not None
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
        assert m is not None
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
        assert m is not None
        process_name = m.group(1)

        exe_name = _iss_define(self.iss_text, "MyAppExeName")
        self.assertIsNotNone(exe_name, "Could not parse MyAppExeName from .iss")
        assert exe_name is not None
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
        assert output_base is not None
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
        assert m is not None
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

    def test_installer_glob_selection_uses_newest_output(self):
        """Older installer files in Output must not be selected after a version bump."""
        self.assertIn("Sort-Object LastWriteTimeUtc -Descending", self.build_ps1_full)


class TestNoStaleProjectNames(unittest.TestCase):
    """No build/installer file should reference the old CV2T / QwenVoiceToText names."""

    _STALE_PATTERNS = re.compile(r"CV2T|QwenVoiceToText|Qwen2-Audio", re.IGNORECASE)

    _FILES_TO_CHECK = [
        "installer/Build-Installer.ps1",
        "installer/speakeasy-setup.iss",
        "speakeasy.spec",
        "speakeasy-cpu.spec",
        "spec_common.py",
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
    """Version strings must agree across package metadata and installer scripts."""

    def test_versions_match(self):
        # speakeasy/__init__.py __version__ is the single source of truth.
        # pyproject.toml derives it dynamically (hatch), so it carries no literal
        # version of its own; the .iss files keep a #define fallback that must
        # stay in sync (Build-Installer injects the real value via /DMyAppVersion).
        package_init = _read("speakeasy/__init__.py")
        m_package = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
        self.assertIsNotNone(m_package, "Could not parse __version__ from speakeasy/__init__.py")
        assert m_package is not None
        version = m_package.group(1)

        pyproject = _read("pyproject.toml")
        self.assertIn(
            'dynamic = ["version"]', pyproject,
            "pyproject.toml must declare a dynamic version sourced from __init__.py",
        )
        self.assertNotRegex(
            pyproject, r'(?m)^version\s*=\s*"',
            "pyproject.toml must not duplicate a literal version; it is dynamic",
        )

        for relpath in ("installer/speakeasy-setup.iss", "installer/speakeasy-cpu-setup.iss"):
            iss_text = _read(relpath)
            m_iss = _iss_define(iss_text, "MyAppVersion")
            self.assertIsNotNone(m_iss, f"Could not parse MyAppVersion from {relpath}")
            assert m_iss is not None
            self.assertEqual(
                version, m_iss,
                f"speakeasy/__init__.py version '{version}' != {relpath} fallback '{m_iss}'",
            )


class TestChangelogAndContractVersion(unittest.TestCase):
    """The CHANGELOG head and the wire contract version must stay in sync with
    the single-source ``__version__`` / ``CONTRACT_VERSION`` constants."""

    @staticmethod
    def _package_version() -> str:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', _read("speakeasy/__init__.py"))
        assert m is not None, "Could not parse __version__"
        return m.group(1)

    def test_changelog_head_matches_package_version(self):
        # The most recent "## [<version>]" entry must describe the version that
        # ships from speakeasy/__init__.py, so the release notes never lag the
        # code (plan §12.1 CHANGELOG-head check).
        changelog = _read("CHANGELOG.md")
        m_head = re.search(r"(?m)^##\s*\[([^\]]+)\]", changelog)
        self.assertIsNotNone(m_head, "CHANGELOG.md has no '## [version]' section")
        assert m_head is not None
        self.assertEqual(
            m_head.group(1), self._package_version(),
            "CHANGELOG.md head version must match speakeasy/__init__.py __version__",
        )

    def test_server_reports_core_contract_version(self):
        # The server's /v1/health contract_version must come from the single
        # core.contract.CONTRACT_VERSION constant, never a hardcoded literal.
        from speakeasy.core.contract import CONTRACT_VERSION

        self.assertIsInstance(CONTRACT_VERSION, int)
        self.assertGreaterEqual(CONTRACT_VERSION, 1)

        server_src = _read("speakeasy/services/server.py")
        self.assertIn("from ..core.contract import CONTRACT_VERSION", server_src)
        self.assertIn('"contract_version": CONTRACT_VERSION', server_src)

    def test_remote_client_checks_core_contract_version(self):
        # The client must reject a server whose contract_version differs from
        # the same core constant (version-skew guard).
        client_src = _read("speakeasy/services/remote_client.py")
        self.assertIn("CONTRACT_VERSION", client_src)
        self.assertIn("RemoteVersionMismatch", client_src)


class TestInstallerProgramDataPaths(unittest.TestCase):
    """Installer app-data paths must follow the runtime ProgramData layout."""

    _ISS_FILES = ("installer/speakeasy-setup.iss", "installer/speakeasy-cpu-setup.iss")

    def test_current_app_data_paths_use_single_define(self):
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            self.assertEqual(
                _iss_define(text, "MyAppDataName"),
                "SpeakEasy AI Granite",
                f"{relpath} must define the current ProgramData app-data directory once.",
            )
            self.assertIn("\\{#MyAppDataName}\\config", text)
            self.assertIn("\\{#MyAppDataName}\\models", text)
            self.assertIn("\\{#MyAppDataName}\\temp", text)

    def test_clean_install_targets_current_granite_config(self):
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            self.assertIn(
                "ConfigDir := ExpandConstant('{commonappdata}') + '\\{#MyAppDataName}\\config';",
                text,
                f"{relpath} clean-install detection must check the active Granite config path.",
            )
            self.assertIn(
                "TempDir   := ExpandConstant('{commonappdata}') + '\\{#MyAppDataName}\\temp';",
                text,
                f"{relpath} clean-install detection must check the active Granite temp path.",
            )
            self.assertNotIn(
                "ExpandConstant('{commonappdata}') + '\\SpeakEasy AI\\config'",
                text,
                f"{relpath} must not clean or migrate into the obsolete non-Granite config path.",
            )

    def test_default_settings_enable_hotkeys_explicitly(self):
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            self.assertIn(
                '"hotkeys_enabled": true',
                text,
                f"{relpath} installer-created settings should make the hotkey default explicit.",
            )

    def test_source_installer_defaults_hotkeys_enabled_when_missing(self):
        text = _read("installer/Install-SpeakEasy-Source.ps1")
        self.assertIn(
            'Match("hotkeys_enabled").Count -eq 0',
            text,
            "Install-SpeakEasy-Source.ps1 must add hotkeys_enabled when missing so "
            "fresh source installs default to enabled global hotkeys.",
        )
        self.assertIn(
            '"hotkeys_enabled" -NotePropertyValue $true',
            text,
            "Install-SpeakEasy-Source.ps1 must default hotkeys_enabled to true on fresh installs.",
        )

    def test_build_install_mode_cleans_programdata_settings(self):
        build_ps1 = _read("installer/Build-Installer.ps1")
        self.assertGreaterEqual(
            build_ps1.count('$dataDir    = "$env:PROGRAMDATA\\SpeakEasy AI Granite"'),
            2,
            "Build-Installer.ps1 Release and Install modes must both clean ProgramData settings.",
        )
        self.assertIn("foreach ($baseDir in @($installDir, $dataDir))", build_ps1)


class TestInstallerDefenderPolicy(unittest.TestCase):
    """Installers must not add Microsoft Defender exclusions by default."""

    _ISS_FILES = ("installer/speakeasy-setup.iss", "installer/speakeasy-cpu-setup.iss")

    def test_inno_installers_do_not_configure_defender_exclusions(self):
        for relpath in self._ISS_FILES:
            text = _read(relpath)
            self.assertNotIn("Add-MpPreference", text)
            self.assertNotIn("Remove-MpPreference", text)
            self.assertNotIn("ExclusionProcess", text)
            self.assertNotIn("ConfigureDefenderExclusions", text)
            self.assertNotIn("Windows Defender exclusions", text)

    def test_source_installer_does_not_configure_defender_exclusions(self):
        text = _read("installer/Install-SpeakEasy-Source.ps1")
        self.assertNotIn("Add-MpPreference", text)
        self.assertNotIn("Remove-MpPreference", text)
        self.assertNotIn("ExclusionProcess", text)


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
        assert torch_src is not None
        self.assertIsNotNone(
            torchaudio_src,
            "pyproject.toml [tool.uv.sources] must pin torchaudio to an explicit index "
            "(mismatched builds cause WinError 127 / 0xc0000139)",
        )
        assert torchaudio_src is not None
        self.assertEqual(
            torch_src.group(1), torchaudio_src.group(1),
            f"torch index '{torch_src.group(1)}' != torchaudio index "
            f"'{torchaudio_src.group(1)}'. Both must use the same CUDA wheel index.",
        )

    def test_installed_torch_torchaudio_major_versions_match(self):
        """Installed torch and torchaudio must share the same major.minor version."""
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import torch, torchaudio; "
                "tv = torch.__version__.split('+')[0].split('.')[:2]; "
                "av = torchaudio.__version__.split('+')[0].split('.')[:2]; "
                "assert tv == av, "
                "f'torch {torch.__version__} / torchaudio {torchaudio.__version__} major mismatch'"
            )],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(
            result.returncode, 0,
            f"torch/torchaudio version mismatch:\n{result.stderr}",
        )

    def test_installed_torch_torchaudio_build_tags_match(self):
        """Both packages must have the same build tag (e.g. +cu128 or both CPU)."""
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import torch, torchaudio; "
                "tt = torch.__version__.partition('+')[2]; "
                "at = torchaudio.__version__.partition('+')[2]; "
                "assert tt == at, "
                "f'torch +{tt} / torchaudio +{at} build tag mismatch'"
            )],
            capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(
            result.returncode, 0,
            f"torch/torchaudio build tag mismatch:\n{result.stderr}",
        )


class TestInstallerHandlesModelDownload(unittest.TestCase):
    """speakeasy-setup.iss must handle the Granite model and bundle the setup script."""

    @classmethod
    def setUpClass(cls):
        cls.iss_text = _read("installer/speakeasy-setup.iss")
        cls.cpu_iss_text = _read("installer/speakeasy-cpu-setup.iss")
        cls.source_installer_text = _read("installer/Install-SpeakEasy-Source.ps1")

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

    def test_installers_request_jsonl_download_progress(self):
        """Both installers must consume structured download progress."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("SPEAKEASY_PROGRESS", text)
                self.assertIn("--progress-format", text)
                self.assertIn("jsonl", text)
                self.assertIn("--progress-file", text)
                self.assertIn("speakeasy-model-download.progress", text)
                self.assertNotIn("SetProgress(0, 1)", text)
                self.assertNotIn("SetProgress(1, 1)", text)

    def test_installer_hotkey_summary_matches_toggle_behavior(self):
        """Installer summaries must show Ctrl+Alt+P as the start/stop toggle."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
            ("Source", self.source_installer_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("Ctrl+Alt+P", text)
                self.assertIn("Start/stop recording", text)
                self.assertNotIn("Ctrl+Alt+L", text)
                self.assertNotIn("Stop recording & transcribe", text)

    def test_installers_surface_model_download_errors(self):
        """Both installers must show and log the captured download failure detail."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("Detail:", text)
                self.assertIn("LastDownloadDetail", text)
                self.assertIn("Model download detail", text)

    def test_installers_do_not_replace_errors_with_xet_warnings(self):
        """Benign Hugging Face/Xet warning output must not hide structured errors."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("function IsDownloadWarning", text)
                self.assertIn("xet storage is enabled", text)
                self.assertIn("IsDownloadWarning(Line)", text)
                self.assertIn("not IsDownloadNoise(Line)", text)
                self.assertIn("LastDownloadDetail = ''", text)

    def test_installers_do_not_replace_errors_with_startup_logs(self):
        """Routine downloader log lines must not become the failure detail."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("function IsDownloadNoise", text)
                self.assertIn("=== speakeasy ai starting", text)
                self.assertIn("unauthenticated requests to the hf hub", text)
                self.assertIn("please set a hf_token", text)
                self.assertIn("[httpx]", text)
                self.assertIn("http request:", text)
                self.assertIn("not IsDownloadNoise(Line)", text)

    def test_installers_accept_complete_model_despite_nonzero_exit(self):
        """If every required model file is on disk, a non-zero downloader exit
        code must not produce a misleading 'Model download failed' error dialog.

        Real-world scenario: snapshot_download finished writing all files, but the
        Python process was terminated (antivirus / OS signal) before it could
        cleanly return EXIT_SUCCESS, leaving an empty stderr and exit code 1.
        """
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("else if GraniteModelExists then", text)
                self.assertIn(
                    "all required model files are present; treating as success.",
                    text,
                )
                self.assertIn(
                    "model files are already present; treating as success.",
                    text,
                )

    def test_frozen_builds_include_hf_xet(self):
        """Xet-backed Hugging Face model downloads need hf_xet in frozen builds."""
        pyproject = _read("pyproject.toml")
        self.assertIn("hf_xet>=", pyproject)
        # Both variants share spec_common.py, which collects the hf_xet libs.
        spec_text = _read("spec_common.py")
        self.assertIn("collect_dynamic_libs('hf_xet')", spec_text)
        self.assertIn("'hf_xet'", spec_text)

    def test_installers_require_full_model_health_for_ready_summary(self):
        """A partial granite directory must not be reported as model-ready."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("ModelExists := GraniteModelExists;", text)
                self.assertIn("tokenizer.json", text)
                self.assertIn("tokenizer_config.json", text)
                self.assertIn("special_tokens_map.json", text)
                self.assertIn("vocab.json", text)
                self.assertIn("model-00003-of-00003.safetensors", text)
                self.assertIn("health check failed", text)

    def test_installers_preflight_model_disk_space(self):
        """Both installers must check free disk space before model download."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("CheckModelDiskSpace", text)
                self.assertIn("PSDrive", text)
                self.assertIn("Not enough free disk space", text)

    def test_installers_quote_model_download_paths(self):
        """Model download paths contain spaces and must be quoted for Start-Process."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("CommandLineQuote(ModelsDir)", text)
                self.assertIn("$argumentLine", text)
                self.assertNotIn("Start-Process -FilePath $exe -ArgumentList $arguments", text)

    def test_installers_recheck_existing_model_before_download(self):
        """Upgrades may skip the dir page, so model detection must run at install time."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                self.assertIn("function GraniteModelExists", text)
                self.assertGreaterEqual(text.count("ModelExists := GraniteModelExists;"), 3)

    def test_model_download_copy_has_enough_height(self):
        """The wrapped model download text must not clip its final line."""
        for name, text in (
            ("GPU", self.iss_text),
            ("CPU", self.cpu_iss_text),
        ):
            with self.subTest(installer=name):
                match = re.search(
                    r"TokenLblSteps\.AutoSize := False;.*?"
                    r"TokenLblSteps\.Height := ScaleY\((\d+)\);",
                    text,
                    re.DOTALL,
                )
                self.assertIsNotNone(
                    match,
                    f"{name} installer must set TokenLblSteps height explicitly.",
                )
                assert match is not None
                self.assertGreaterEqual(
                    int(match.group(1)),
                    72,
                    f"{name} installer TokenLblSteps height is too small for wrapped copy.",
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

    _REPO_SLUG = "kwp490/speakeasy-granite"

    @classmethod
    def setUpClass(cls):
        cls.readme = _read("README.md")
        # pyproject.toml is dynamic now; __version__ is the source of truth.
        m = re.search(r'__version__\s*=\s*"([^"]+)"', _read("speakeasy/__init__.py"))
        assert m, "Could not parse __version__ from speakeasy/__init__.py"
        cls.version = m.group(1)

    def test_no_wrong_repo_slug_in_links(self):
        """No github.com URL in README should use a repo name other than kwp490/speakeasy-granite."""
        wrong = re.findall(
            r"https://github\.com/kwp490/(?!speakeasy-granite(?:\.git)?[/\s)\]])([\w.-]+)",
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


