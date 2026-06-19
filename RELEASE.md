# Release Checklist

Step-by-step checklist for publishing a new SpeakEasy AI release.

## Pre-release

- [ ] **Bump version** in `speakeasy/__init__.py` (`__version__ = "X.Y.Z"`)
  — this is the single source of truth. `pyproject.toml` derives it dynamically
  (`[tool.hatch.version]`), and `installer/Build-Installer.ps1` reads it to inject
  `/DMyAppVersion` into Inno Setup, so installer filenames follow automatically.
  Keep the `#define MyAppVersion` fallback in both `installer/*.iss` files and the
  README release links in sync (enforced by `tests/test_build_naming.py` and
  `tests/test_installer_version_consistency.py`).
- [ ] **Finalize changelog** in `CHANGELOG.md`:
  - Rename `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`
  - Add a fresh `## [Unreleased]` section above it
- [ ] **Update supported versions** in `SECURITY.md` to include the new `X.Y.x` line.
- [ ] **Run the settings-migration check** — confirm a real `settings.json` written by
  the previous release loads cleanly into the new build (no destructive `model_path`
  reset for offline custom/UNC paths). `tests/test_settings_migration.py` covers the
  matrix; for a real-world check, copy an old `settings.json` into the active
  `%ProgramData%\SpeakEasy AI Granite\config` and launch the app once.
- [ ] **Run the benchmark diff** — on benchmark hardware, run
  `uv run python tools/bench.py --device {cuda,cpu}` and compare WER + p50/p95
  latency against `docs/benchmarks/baseline-0.14.5.md` (WER within 0.5 abs). For a
  quick zero-dependency smoke, `uv run python tools/bench.py --smoke`.
- [ ] Commit the version bump, changelog, and security updates together.

## Local Validation (optional)

Run the full local release cycle to verify both build variants before tagging.
Requires admin (the script auto-elevates).

```powershell
.\installer\Build-Installer.ps1 -Mode Release              # GPU variant
.\installer\Build-Installer.ps1 -Mode Release -Variant CPU  # CPU variant
```

This runs the test suite, builds via PyInstaller + Inno Setup, uninstalls the
previous version, installs the new build, validates the frozen bundle, and
launches the app.

- [ ] **Measure the built installer sizes** and update the README download table
  (the GPU+CPU and CPU `Size` column) with the actual `.exe` sizes from this build,
  e.g. `Get-Item installer\Output\*.exe | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,0)}}`.

## Tag & Push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a `v*` tag triggers [`.github/workflows/release.yml`](.github/workflows/release.yml),
which creates a draft GitHub Release using `.github/RELEASE_NOTES.md` as the
release body.

Installer builds are local-only. Attach the locally generated GPU and CPU
installer `.exe` files, plus their checksum file, to the draft release before
publishing it.

## Post-release

- [ ] **Upload release assets** — attach both locally built installers and
  `SHA256SUMS.txt` to the draft release.
- [ ] **Verify the GitHub Release** — confirm both installers and `SHA256SUMS.txt`
  are listed and download links work before publishing.
- [ ] **Verify the SmartScreen pre-warning** — confirm the release body starts with
  the "Before You Install" note from `.github/RELEASE_NOTES.md` before any
  download links are shared.
- [ ] **Hide the previous release** — mark the prior GitHub Release as a draft or
      pre-release so the README download badge points to the new version only.
