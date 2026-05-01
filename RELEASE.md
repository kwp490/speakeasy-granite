# Release Checklist

Step-by-step checklist for publishing a new SpeakEasy AI release.

## Pre-release

- [ ] **Bump version** in `pyproject.toml` (`version = "X.Y.Z"`)
  — this is the single source of truth; installer filenames derive from it.
- [ ] **Finalize changelog** in `CHANGELOG.md`:
  - Rename `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`
  - Add a fresh `## [Unreleased]` section above it
- [ ] **Update supported versions** in `SECURITY.md` to include the new `X.Y.x` line.
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

## Tag & Push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a `v*` tag triggers [`.github/workflows/release.yml`](.github/workflows/release.yml),
which:

1. Builds both GPU and CPU installers in CI
2. Generates `SHA256SUMS.txt` for both `.exe` files
3. Creates a public GitHub Release with all assets attached

## Post-release

- [ ] **Verify the GitHub Release** — confirm both installers and `SHA256SUMS.txt`
      are listed and download links work.
- [ ] **Hide the previous release** — mark the prior GitHub Release as a draft or
      pre-release so the README download badge points to the new version only.
