"""Tests that the application icon is properly configured.

Verifies:
    - SetCurrentProcessExplicitAppUserModelID is called before QApplication.
    - app.ico exists in the assets directory.
    - MainWindow.__init__ sets a window icon.
    - DeveloperPanel.__init__ sets a window icon.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from speakeasy import app_identity

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAIN_PY = _REPO_ROOT / "speakeasy" / "__main__.py"
_MAIN_WINDOW_PY = _REPO_ROOT / "speakeasy" / "main_window.py"
_DEV_PANEL_PY = _REPO_ROOT / "speakeasy" / "developer_panel.py"
_ASSETS_DIR = _REPO_ROOT / "speakeasy" / "assets"
_GPU_SPEC = _REPO_ROOT / "speakeasy.spec"
_CPU_SPEC = _REPO_ROOT / "speakeasy-cpu.spec"
_GPU_INSTALLER = _REPO_ROOT / "installer" / "speakeasy-setup.iss"
_CPU_INSTALLER = _REPO_ROOT / "installer" / "speakeasy-cpu-setup.iss"


class TestAppIconExists(unittest.TestCase):
    """The app.ico file must be present in the assets directory."""

    def test_app_ico_exists(self):
        ico = _ASSETS_DIR / "app.ico"
        self.assertTrue(ico.is_file(), f"Missing {ico}")

    def test_app_ico_is_valid_ico(self):
        ico = _ASSETS_DIR / "app.ico"
        header = ico.read_bytes()[:6]
        self.assertEqual(header[:4], b"\x00\x00\x01\x00", f"Invalid ICO header in {ico}")
        self.assertGreater(int.from_bytes(header[4:6], "little"), 0, f"No icons in {ico}")


class TestAppIconPath(unittest.TestCase):
    """The runtime icon path must match the PyInstaller package-data layout."""

    def test_source_icon_path_exists(self):
        self.assertEqual(app_identity.app_icon_path(), _ASSETS_DIR / "app.ico")
        self.assertTrue(app_identity.app_icon_path().is_file())

    def test_frozen_icon_path_uses_package_assets_not_meipass_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            package_dir = bundle_root / "speakeasy"
            icon_path = package_dir / "assets" / "app.ico"
            icon_path.parent.mkdir(parents=True)
            icon_path.write_bytes(b"\x00\x00\x01\x00\x01\x00")

            with mock.patch.object(app_identity, "__file__", str(package_dir / "app_identity.py")):
                with mock.patch.object(sys, "_MEIPASS", str(bundle_root), create=True):
                    self.assertEqual(app_identity.app_icon_path(), icon_path)
                    self.assertTrue(app_identity.app_icon_path().is_file())


class TestPyInstallerIconConfiguration(unittest.TestCase):
    """Frozen builds must bundle and embed the application icon."""

    def test_specs_collect_app_icon_in_package_assets(self):
        for spec_path in (_GPU_SPEC, _CPU_SPEC):
            source = spec_path.read_text(encoding="utf-8")
            self.assertRegex(
                source,
                r"\(['\"]speakeasy/assets['\"],\s*['\"]speakeasy/assets['\"]\)",
                f"{spec_path.name} must collect app.ico under speakeasy/assets",
            )

    def test_specs_embed_app_icon_in_exe(self):
        for spec_path in (_GPU_SPEC, _CPU_SPEC):
            source = spec_path.read_text(encoding="utf-8")
            self.assertRegex(
                source,
                r"icon\s*=\s*['\"]speakeasy/assets/app\.ico['\"]",
                f"{spec_path.name} must embed app.ico into speakeasy.exe",
            )


class TestAppUserModelID(unittest.TestCase):
    """SetCurrentProcessExplicitAppUserModelID must be called in __main__.py
    before QApplication is created, so Windows 11 taskbar shows our icon."""

    @classmethod
    def setUpClass(cls):
        cls._source = _MAIN_PY.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source, filename="__main__.py")

    def test_app_user_model_id_is_set(self):
        """Source must contain SetCurrentProcessExplicitAppUserModelID."""
        self.assertIn(
            "SetCurrentProcessExplicitAppUserModelID",
            self._source,
            "__main__.py must call SetCurrentProcessExplicitAppUserModelID "
            "so the Windows taskbar associates our icon with the app.",
        )

    def test_qapplication_icon_uses_shared_icon_path(self):
        """QApplication icon must use the same path as app windows."""
        self.assertIn("app_icon_path", self._source)
        self.assertIn("app.setWindowIcon", self._source)

    def test_app_user_model_id_before_qapplication(self):
        """AppUserModelID must be set before QApplication() is constructed."""
        model_id_line = None
        qapp_construct_line = None
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Attribute):
                if getattr(node, 'attr', '') == 'SetCurrentProcessExplicitAppUserModelID':
                    model_id_line = node.lineno
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == 'QApplication':
                    if any(isinstance(a, ast.Attribute) and a.attr == 'argv' for a in node.args):
                        if qapp_construct_line is None:
                            qapp_construct_line = node.lineno
        self.assertIsNotNone(model_id_line, "Could not find AppUserModelID call")
        self.assertIsNotNone(qapp_construct_line, "Could not find QApplication() call")
        self.assertLess(
            model_id_line, qapp_construct_line,
            "SetCurrentProcessExplicitAppUserModelID must be called BEFORE "
            f"QApplication() (line {model_id_line} vs {qapp_construct_line})",
        )

    def test_installer_shortcuts_use_process_app_user_model_id(self):
        """Installed shortcuts must advertise the same AppUserModelID as the app."""
        expected_define = f'#define MyAppUserModelID "{app_identity.APP_USER_MODEL_ID}"'
        for installer_path in (_GPU_INSTALLER, _CPU_INSTALLER):
            source = installer_path.read_text(encoding="utf-8")
            self.assertIn(
                expected_define,
                source,
                f"{installer_path.name} must define the same AppUserModelID as the app",
            )
            self.assertGreaterEqual(
                source.count('AppUserModelID: "{#MyAppUserModelID}"'),
                2,
                f"{installer_path.name} must set AppUserModelID on desktop and Start Menu shortcuts",
            )


class TestWindowIconSetOnWindows(unittest.TestCase):
    """Both MainWindow and DeveloperPanel must call setWindowIcon."""

    def test_main_window_sets_icon(self):
        source = _MAIN_WINDOW_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename="main_window.py")
        mw_class = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "MainWindow"),
            None,
        )
        self.assertIsNotNone(mw_class, "MainWindow class not found")
        init_method = next(
            (n for n in ast.walk(mw_class)
             if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        self.assertIsNotNone(init_method, "MainWindow.__init__ not found")
        init_source = ast.get_source_segment(source, init_method)
        self.assertIn(
            "setWindowIcon",
            init_source,
            "MainWindow.__init__ must call setWindowIcon so the Windows 11 "
            "taskbar displays the app icon.",
        )
        self.assertIn("app_icon_path", init_source)

    def test_developer_panel_sets_icon(self):
        source = _DEV_PANEL_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename="developer_panel.py")
        dp_class = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "DeveloperPanel"),
            None,
        )
        self.assertIsNotNone(dp_class, "DeveloperPanel class not found")
        init_method = next(
            (n for n in ast.walk(dp_class)
             if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        self.assertIsNotNone(init_method, "DeveloperPanel.__init__ not found")
        init_source = ast.get_source_segment(source, init_method)
        self.assertIn(
            "setWindowIcon",
            init_source,
            "DeveloperPanel.__init__ must call setWindowIcon so the Windows 11 "
            "taskbar displays the app icon.",
        )
        self.assertIn("app_icon_path", init_source)


if __name__ == "__main__":
    unittest.main()
