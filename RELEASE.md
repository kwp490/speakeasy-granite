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
