<#
.SYNOPSIS
    Build, test, and launch SpeakEasy AI -- all-in-one build and development tool.

.DESCRIPTION
    Three operating modes:

      Build (default when -Mode Build is specified)
        PyInstaller binary + Inno Setup installer. Two-step build:
          1. pyinstaller speakeasy.spec  -> dist/speakeasy/
          2. iscc installer/speakeasy-setup.iss -> installer/Output/SpeakEasy-AI-Granite-Setup-<version>.exe

      Release
        Full release cycle: syncs dependencies, runs the test suite, builds
        the installer (PyInstaller + Inno Setup), silently uninstalls the old
        version (keeping models), silently installs the new build, validates
        the frozen bundle, and launches speakeasy.exe.  Requires admin --
        auto-elevates if needed.

      Source
        Runs directly from source with SPEAKEASY_HOME pointed at a dev-temp
        folder.  No system changes -- the installed release build is untouched.

      Install
        Silently install a previously-built installer package.  Finds the
        latest matching setup .exe in installer/Output/ for the chosen
        -Variant (GPU or CPU), uninstalls any existing version, cleans
        leftover settings, and silently installs the new build.  Requires
        admin -- auto-elevates if needed.

    When -Mode is not specified an interactive menu is shown.

    Supports GPU (default), CPU, or Both variants via the -Variant parameter.

    Run from the repository root or from installer/. Requires:
      - Python venv with PyInstaller (uv sync --extra dev)
      - Inno Setup 6.x with iscc.exe on PATH or at the default install location
        (Build and Release modes only)

.PARAMETER Mode
    Operating mode: Build, Release, Source, or Install.
      - Build:   compile PyInstaller binary + Inno Setup installer (default)
      - Release: build + install + validate + launch (requires admin)
      - Source:  run from source via dev-temp (no system changes)
      - Install: silently install a pre-built installer (requires admin)
    When omitted an interactive menu is shown.

.PARAMETER Variant
    Build variant: GPU (default), CPU, or Both.
      - GPU:  builds with speakeasy.spec + speakeasy-setup.iss (CUDA-enabled)
      - CPU:  builds with speakeasy-cpu.spec + speakeasy-cpu-setup.iss (no CUDA, smaller)
      - Both: builds GPU first, then CPU sequentially

.PARAMETER SkipTests
    Skip the pytest test suite.  Useful when iterating on non-test changes
    and you want a faster cycle.

.PARAMETER Clean
    In Build/Release mode, force a fresh PyInstaller rebuild (passes --clean).
    In Source mode, reset dev-temp config/logs/temp before launch so stale
    development settings do not leak into the session.

.PARAMETER InnoOnly
    (Build mode only) Skip the PyInstaller step and jump straight to Inno
    Setup compilation.  Useful when iterating on installer UI or Pascal code
    without changing the application binary.

.PARAMETER Fast
    Use fast compression for Inno Setup (lzma2/fast, non-solid) instead of
    the release-quality lzma2/ultra64 solid compression.  Produces a larger
    installer but compiles much faster.  Intended for dev/test builds.

.EXAMPLE
    # --------------------------------------------------------------------------
    # INTERACTIVE
    # --------------------------------------------------------------------------
    .\installer\Build-Installer.ps1
        # Shows a numbered menu to choose mode and variant. No arguments needed.
        # Does NOT install or uninstall anything until you select a menu option.

    # --------------------------------------------------------------------------
    # BUILD  --  Produces installer .exe files in installer\Output\.
    #            Runs the test suite first. NO system changes (no install/uninstall).
    # --------------------------------------------------------------------------
    .\installer\Build-Installer.ps1 -Mode Build
        # Runs tests, then builds the GPU installer (PyInstaller + Inno Setup).
        # Skips PyInstaller if source files are unchanged since last build (hash cache).

    .\installer\Build-Installer.ps1 -Mode Build -Variant CPU
        # Same as above but builds the CPU (no CUDA) installer instead.

    .\installer\Build-Installer.ps1 -Mode Build -Variant Both
        # Builds the GPU installer first, then the CPU installer sequentially.
        # Produces two .exe files in installer\Output\.

    .\installer\Build-Installer.ps1 -Mode Build -Clean
        # Forces a full PyInstaller rebuild (ignores the hash cache), then packages.
        # Use when PyInstaller output may be stale despite no source changes.

    .\installer\Build-Installer.ps1 -Mode Build -Fast
        # Builds with fast Inno Setup compression -- larger .exe, much faster compile.
        # Useful for dev/test iterations where file size does not matter.

    .\installer\Build-Installer.ps1 -Mode Build -InnoOnly -Fast
        # Skips PyInstaller entirely and re-runs Inno Setup on the existing dist\ folder.
        # Use when only installer scripts or assets changed (not Python source).

    # --------------------------------------------------------------------------
    # RELEASE  --  Full cycle: build -> UNINSTALL old -> INSTALL new -> launch.
    #              Requires admin (auto-elevates). Models are always preserved.
    # --------------------------------------------------------------------------
    .\installer\Build-Installer.ps1 -Mode Release
        # Runs tests, builds the GPU installer (release compression), silently
        # UNINSTALLS the existing SpeakEasy AI, INSTALLS the new build, validates
        # the frozen bundle, then launches speakeasy.exe.

    .\installer\Build-Installer.ps1 -Mode Release -Variant CPU
        # Same full release cycle but builds, installs, and launches the CPU variant.

    .\installer\Build-Installer.ps1 -Mode Release -Fast
        # Release cycle with fast Inno Setup compression (dev/test use).
        # Still UNINSTALLS old and INSTALLS new -- just a larger installer file.

    .\installer\Build-Installer.ps1 -Mode Release -SkipTests
        # Release cycle without running the test suite first.

    .\installer\Build-Installer.ps1 -Mode Release -Clean
        # Release cycle with a forced full PyInstaller rebuild before packaging.

    # --------------------------------------------------------------------------
    # INSTALL  --  UNINSTALL old -> INSTALL a pre-built .exe -> launch.
    #              Run 'Mode Build' first to produce the installer.
    #              Requires admin (auto-elevates). Models are always preserved.
    # --------------------------------------------------------------------------
    .\installer\Build-Installer.ps1 -Mode Install
        # Finds the latest GPU installer in installer\Output\, silently UNINSTALLS
        # any existing version, INSTALLS the new build, then launches speakeasy.exe.

    .\installer\Build-Installer.ps1 -Mode Install -Variant CPU
        # Same as above but finds and installs the latest CPU installer instead.

    # --------------------------------------------------------------------------
    # SOURCE  --  Runs the app directly from source code. NO install or uninstall.
    #             Any installed release build is completely untouched.
    # --------------------------------------------------------------------------
    .\installer\Build-Installer.ps1 -Mode Source
        # Runs tests, then launches the app from source using dev-temp\ for
        # config, logs, and temp files. Nothing is installed or changed system-wide.

    .\installer\Build-Installer.ps1 -Mode Source -Clean
        # Wipes dev-temp config/logs/temp for a clean slate, then runs from source.
        # Use when stale dev settings are causing unexpected behavior.

    .\installer\Build-Installer.ps1 -Mode Source -SkipTests
        # Skips the test suite and launches from source immediately.

.NOTES
    Run from the repository root.
#>

[CmdletBinding()]
param(
    [ValidateSet('Build', 'Release', 'Source', 'Install')]
    [string]$Mode,

    [ValidateSet('GPU', 'CPU', 'Both')]
    [string]$Variant = 'GPU',

    [switch]$SkipTests,

    [switch]$Clean,

    [switch]$InnoOnly,

    [switch]$Fast
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -- Suppress Windows "Location is not available" dialogs -----------------------
# SEM_FAILCRITICALERRORS (0x0001) + SEM_NOOPENFILEERRORBOX (0x8000) tells the
# kernel to return errors to the calling process instead of popping a dialog
# when an inaccessible drive (e.g. a removed D:\ volume) is touched during
# junction setup, torch swap, or PyInstaller I/O.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class WinErrorMode {
    [DllImport("kernel32.dll")]
    public static extern uint SetErrorMode(uint uMode);
}
'@ -ErrorAction SilentlyContinue
try {
    [WinErrorMode]::SetErrorMode(0x8001) | Out-Null   # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
} catch { }

# -- Resolve repo root (works whether invoked from repo root or installer/) ----
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Split-Path -Leaf $scriptDir) -eq 'installer') {
    $RepoRoot = Split-Path -Parent $scriptDir
} else {
    $RepoRoot = $scriptDir
}
Push-Location $RepoRoot

# -- Helpers -------------------------------------------------------------------
function Write-Step($msg)  { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "  [ERROR] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "  $msg" -ForegroundColor DarkGray }

function Get-RelativeFileList([string]$RootPath) {
    if (-not (Test-Path $RootPath)) { return @() }
    $root = (Resolve-Path $RootPath).Path
    return Get-ChildItem -Path $root -Recurse -File |
        ForEach-Object { $_.FullName.Substring($root.Length).TrimStart('\\') } |
        Sort-Object -Unique
}

function Exit-Script([int]$code = 1) {
    Pop-Location
    exit $code
}


# -- Interactive menu ----------------------------------------------------------
if (-not $Mode) {
    Write-Host ""
    Write-Host "  =================================================" -ForegroundColor Cyan
    Write-Host "       SpeakEasy AI -- Build & Test Launcher         " -ForegroundColor Cyan
    Write-Host "  =================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  BUILD" -ForegroundColor White
    Write-Host "  -----" -ForegroundColor DarkGray
    Write-Host "  1) Build GPU installer                   " -ForegroundColor White
    Write-Host "     PyInstaller + Inno Setup (CUDA)       " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  2) Build CPU installer                   " -ForegroundColor White
    Write-Host "     PyInstaller + Inno Setup (no CUDA)    " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  3) Build Both installers                 " -ForegroundColor White
    Write-Host "     GPU first, then CPU                   " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  TEST & LAUNCH" -ForegroundColor White
    Write-Host "  -------------" -ForegroundColor DarkGray
    Write-Host "  4) Release Test                          " -ForegroundColor White
    Write-Host "     Build, install, verify, launch .exe   " -ForegroundColor DarkGray
    Write-Host "     (requires admin)                      " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  5) Source Test                           " -ForegroundColor White
    Write-Host "     Run from source, no system changes    " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  INSTALL" -ForegroundColor White
    Write-Host "  -------" -ForegroundColor DarkGray
    Write-Host "  6) Install GPU build                     " -ForegroundColor White
    Write-Host "     Silent-install latest GPU .exe         " -ForegroundColor DarkGray
    Write-Host "     (requires admin)                      " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  7) Install CPU build                     " -ForegroundColor White
    Write-Host "     Silent-install latest CPU .exe         " -ForegroundColor DarkGray
    Write-Host "     (requires admin)                      " -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Q) Quit                                  " -ForegroundColor White
    Write-Host "  =================================================" -ForegroundColor Cyan
    Write-Host ""

    $choice = Read-Host "  Select an option"
    switch ($choice.ToLower()) {
        '1' { $Mode = 'Build';   $Variant = 'GPU'  }
        '2' { $Mode = 'Build';   $Variant = 'CPU'  }
        '3' { $Mode = 'Build';   $Variant = 'Both' }
        '4' { $Mode = 'Release' }
        '5' { $Mode = 'Source'  }
        '6' { $Mode = 'Install'; $Variant = 'GPU' }
        '7' { $Mode = 'Install'; $Variant = 'CPU' }
        'q' { Write-Host "  Bye."; Exit-Script 0 }
        default {
            Write-Err "Invalid choice '$choice'"
            Exit-Script 1
        }
    }
}

Write-Step "Mode: $Mode | Variant: $Variant"


# â”€â”€ RAM disk drive letter (change this if R: conflicts) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
$RamDiskDrive = 'R:'

# â”€â”€ RAM disk junction helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Creates NTFS junctions from build/ and dist/ to folders on a RAM disk so
# PyInstaller I/O (thousands of files in torch/transformers) hits ~100ns RAM
# latency instead of ~6Âµs NVMe latency.  All downstream consumers (Inno Setup,
# tests) see the same repo-relative paths.
function Initialize-RamDiskJunctions {
    if (-not (Test-Path $RamDiskDrive)) {
        # RAM disk not mounted -- try to auto-provision with AIM Toolkit (aim_ll)
        $aimLl = if (Test-Path "$env:ProgramFiles\AIM Toolkit\aim_ll.exe") {
            "$env:ProgramFiles\AIM Toolkit\aim_ll.exe"
        } else {
            (Get-Command aim_ll -ErrorAction SilentlyContinue).Source
        }
        if (-not $aimLl) {
            Write-Warn "RAM disk $RamDiskDrive is not available."
            Write-Info "Install AIM Toolkit: https://sourceforge.net/projects/aim-toolkit/"
            Write-Info "Or mount any writable RAM disk as $RamDiskDrive."
            Write-Info "(AIM Toolkit supersedes ImDisk Toolkit for recent Windows versions.)"
            return
        }

        Write-Info "Provisioning 12 GB RAM disk on ${RamDiskDrive} via AIM Toolkit..."
        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $aimLl -a -t vm -s 12G -m $RamDiskDrive -p "/fs:ntfs /q /y" 2>&1 |
                ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        } finally {
            $ErrorActionPreference = $prevPref
        }

        if (-not (Test-Path $RamDiskDrive)) {
            Write-Warn "Failed to create RAM disk. Using local build/dist directories."
            return
        }
        Write-Ok "RAM disk provisioned on $RamDiskDrive (12 GB, NTFS)"
    } else {
        # Verify the existing drive is writable
        $testFile = Join-Path $RamDiskDrive '.speakeasy-write-test'
        try {
            [IO.File]::WriteAllText($testFile, 'ok')
            Remove-Item $testFile -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warn "RAM disk $RamDiskDrive exists but is not writable. Using local build/dist directories."
            return
        }
        $drive     = Get-PSDrive ($RamDiskDrive.TrimEnd(':'))
        $totalGB   = [math]::Round(($drive.Free + $drive.Used) / 1GB, 1)
        $freeGB    = [math]::Round($drive.Free / 1GB, 1)

        # Auto-extend if disk is undersized (e.g. provisioned at old 10 GB size)
        if ($totalGB -lt 11) {
            $aimLl = if (Test-Path "$env:ProgramFiles\AIM Toolkit\aim_ll.exe") {
                "$env:ProgramFiles\AIM Toolkit\aim_ll.exe"
            } else {
                (Get-Command aim_ll -ErrorAction SilentlyContinue).Source
            }
            if ($aimLl) {
                Write-Info "RAM disk is ${totalGB} GB; attempting to extend to 12 GB..."
                # aim_ll -e needs the 6-digit SCSI unit number; obtain it from -l output
                $listOut = & $aimLl -l -m $RamDiskDrive 2>&1 | Out-String
                $unitNum = ([regex]::Match($listOut, '(?m)^\s*([0-9a-fA-F]{6})\b')).Groups[1].Value
                if ($unitNum) {
                    $prevPref = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
                    try {
                        & $aimLl -e -s 12G -u $unitNum 2>&1 |
                            ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
                    } finally { $ErrorActionPreference = $prevPref }
                    # Extend the NTFS volume to fill the enlarged virtual disk
                    $letter  = $RamDiskDrive.TrimEnd(':')
                    $diskNum = (Get-Partition | Where-Object { $_.DriveLetter -eq $letter }).DiskNumber
                    $partNum = (Get-Partition | Where-Object { $_.DriveLetter -eq $letter }).PartitionNumber
                    if ($null -ne $diskNum) {
                        "select disk $diskNum`nselect partition $partNum`nextend" |
                            diskpart | Out-Null
                    }
                    $drive   = Get-PSDrive ($RamDiskDrive.TrimEnd(':'))
                    $totalGB = [math]::Round(($drive.Free + $drive.Used) / 1GB, 1)
                    $freeGB  = [math]::Round($drive.Free / 1GB, 1)
                    if ($totalGB -ge 11) {
                        Write-Ok "RAM disk extended to ${totalGB} GB (${freeGB} GB free)"
                    } else {
                        Write-Warn "Extend may not have taken effect yet (${totalGB} GB total). " +
                                   "Use RamDiskUI.exe to resize $RamDiskDrive to 12 GB manually."
                    }
                } else {
                    Write-Warn "Could not determine device unit for $RamDiskDrive. " +
                               "Use RamDiskUI.exe to resize to 12 GB manually."
                }
            } else {
                Write-Warn "RAM disk $RamDiskDrive is ${totalGB} GB (target: 12 GB). " +
                           "Use RamDiskUI.exe to resize manually."
            }
        }

        if ($freeGB -lt 5) {
            Write-Warn "RAM disk $RamDiskDrive has only ${freeGB} GB free (recommend >= 5 GB)"
        }
        Write-Ok "RAM disk $RamDiskDrive already mounted (${freeGB} GB free)"
    }

    foreach ($pair in @(
        @{ Local = 'build'; Remote = "$RamDiskDrive\speakeasy-build" },
        @{ Local = 'dist';  Remote = "$RamDiskDrive\speakeasy-dist" }
    )) {
        $local  = $pair.Local
        $remote = $pair.Remote

        # Ensure remote target exists
        if (-not (Test-Path $remote)) {
            New-Item -ItemType Directory -Path $remote -Force | Out-Null
        }

        # If local path is already a junction pointing to the right target, no-op
        if (Test-Path $local) {
            $item = Get-Item $local -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                $target = ($item | Select-Object -ExpandProperty Target) 2>$null
                if ($target -eq $remote) {
                    Write-Ok "$local -> $remote (junction exists)"
                    continue
                }
                # Junction points elsewhere -- remove it
                cmd /c rmdir "$local" | Out-Null
            } else {
                # Real directory -- migrate contents to RAM disk, then remove
                if ((Get-ChildItem $local -Force | Measure-Object).Count -gt 0) {
                    Write-Info "Migrating $local contents to $remote..."
                    Get-ChildItem $local -Force | Move-Item -Destination $remote -Force
                }
                Remove-Item $local -Recurse -Force
            }
        }

        # Create junction
        cmd /c mklink /J "$local" "$remote" | Out-Null
        if (Test-Path $local) {
            Write-Ok "$local -> $remote (junction created)"
        } else {
            Write-Warn "Failed to create junction $local -> $remote"
        }
    }
}

# â”€â”€ Source-hash helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Computes a hash over all files that affect the PyInstaller output so we can
# skip the (slow) PyInstaller step when nothing has changed.
function Get-SourceHash {
    param([string]$VariantTag = 'gpu')
    $hashInput = @()
    # Python source + spec + project config
    $files = @(Get-ChildItem -Path "speakeasy" -Recurse -Include "*.py" -File) +
             @(Get-Item "speakeasy.spec") +
             @(Get-Item "pyproject.toml")
    if ($VariantTag -eq 'cpu' -and (Test-Path 'speakeasy-cpu.spec')) {
        $files += @(Get-Item 'speakeasy-cpu.spec')
    }
    foreach ($f in $files | Sort-Object FullName) {
        $h = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
        $hashInput += "$($f.FullName)|$h"
    }
    # Include variant tag in hash to prevent cross-variant cache hits
    $hashInput += "VARIANT=$VariantTag"
    # Hash the combined list
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($hashInput -join "`n")
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '')
}

$HashFile = "build\.speakeasy-build-hash"
$CpuHashFile = "build\.speakeasy-cpu-build-hash"


# ==============================================================================
#  PHASE 1 -- Pre-flight checks (shared, skipped for Install mode)
# ==============================================================================

if ($Mode -ne 'Install') {

Write-Step "Pre-flight checks..."

# 1a. Verify uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Err "uv not found on PATH."
    Write-Info "Install it: irm https://astral.sh/uv/install.ps1 | iex"
    Exit-Script 1
}
Write-Ok "uv found: $(uv --version 2>$null)"

# 1b. Verify pyproject.toml exists
if (-not (Test-Path "pyproject.toml")) {
    Write-Err "pyproject.toml not found. Run this script from the repository root."
    Exit-Script 1
}
Write-Ok "pyproject.toml found"

# 1c. Verify spec files (Build and Release modes)
if ($Mode -in @('Build', 'Release')) {
    if (-not (Test-Path "speakeasy.spec")) {
        Write-Err "speakeasy.spec not found. Run this script from the repository root."
        Exit-Script 1
    }
    Write-Ok "speakeasy.spec found"
    if ($Variant -in @('CPU', 'Both') -and -not (Test-Path 'speakeasy-cpu.spec')) {
        Write-Err "speakeasy-cpu.spec not found. Required for CPU variant."
        Exit-Script 1
    }
    if ($Variant -in @('CPU', 'Both')) { Write-Ok 'speakeasy-cpu.spec found' }
}

# 1d. Find iscc.exe (Build and Release modes only)
$iscc = $null
if ($Mode -in @('Build', 'Release')) {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $defaultPaths = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        foreach ($p in $defaultPaths) {
            if (Test-Path $p) {
                $iscc = Get-Item $p
                break
            }
        }
    }
    if (-not $iscc) {
        Write-Err "Inno Setup compiler (iscc.exe) not found."
        Write-Info "Install it: winget install JRSoftware.InnoSetup"
        Write-Info "Or download from https://jrsoftware.org/isdl.php"
        Exit-Script 1
    }
    Write-Ok "Inno Setup found: $($iscc)"
}

# 1e. Sync dependencies
Write-Step "Syncing dependencies (uv sync --extra dev)..."
$prevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    uv sync --extra dev 2>&1 | ForEach-Object { Write-Host "  $_" }
} finally {
    $ErrorActionPreference = $prevPref
}
if ($LASTEXITCODE -ne 0) {
    Write-Err "uv sync failed (exit code $LASTEXITCODE)."
    Exit-Script 1
}
Write-Ok "Dependencies synced"

# 1f. Verify torch/torchaudio compatibility (mismatched builds cause WinError 127)
# Only relevant for GPU variant -- CPU builds don't use torchaudio.
if ($Variant -in @('GPU', 'Both')) {
    Write-Step "Checking torch / torchaudio compatibility..."
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $torchCheck = uv run python -c "
import torch, torchaudio, sys
tv = torch.__version__; tav = torchaudio.__version__
t_base = tv.split('+')[0]; ta_base = tav.split('+')[0]
t_tag = tv.partition('+')[2]; ta_tag = tav.partition('+')[2]
ok = True
if t_base.rsplit('.', 1)[0] != ta_base.rsplit('.', 1)[0]:
    print(f'FAIL: torch {tv} and torchaudio {tav} have mismatched major versions')
    ok = False
if t_tag != ta_tag:
    print(f'FAIL: torch build +{t_tag} != torchaudio build +{ta_tag} (CUDA/CPU mismatch)')
    ok = False
if ok:
    print(f'OK: torch={tv}  torchaudio={tav}')
sys.exit(0 if ok else 1)
" 2>&1
    $ErrorActionPreference = $prevPref
    $torchCheck | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "torch/torchaudio mismatch will cause DLL load failures at runtime."
        Write-Info "Fix: ensure both use the same index in pyproject.toml [tool.uv.sources], then run 'uv sync'."
        Exit-Script 1
    }
    Write-Ok "torch/torchaudio compatible"
} else {
    Write-Step "Skipping torch/torchaudio check (CPU variant)"
    Write-Ok "CPU variant -- torchaudio not used"
}

} # end pre-flight checks (skipped for Install mode)


# â”€â”€ RAM disk junctions (Build and Release modes) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Always use the RAM disk for builds.  If the drive is not mounted, attempt to
# provision one via AIM Toolkit (aim_ll).  The junction helper falls back
# gracefully to local build/dist directories if the drive cannot be created.
if ($Mode -in @('Build', 'Release')) {
    Write-Step "Setting up RAM disk junctions..."
    Initialize-RamDiskJunctions
}


# ==============================================================================
#  PHASE 2 -- Run test suite (shared, skipped for Install mode)
# ==============================================================================

if ($Mode -ne 'Install') {

# In Release mode, pytest runs before the fresh PyInstaller build. Remove any
# stale dist/ tree first so frozen-build dist assertions do not read an old bundle.
if ($Mode -eq 'Release') {
    $staleDirs = switch ($Variant) {
        'GPU'  { @('dist\speakeasy') }
        'CPU'  { @('dist\speakeasy-cpu') }
        'Both' { @('dist\speakeasy', 'dist\speakeasy-cpu') }
    }
    foreach ($staleDistDir in $staleDirs) {
        if (Test-Path $staleDistDir) {
            Remove-Item $staleDistDir -Recurse -Force
            Write-Ok "Removed stale $staleDistDir before pre-build tests"
        }
    }
}

if ($SkipTests) {
    Write-Warn "Test suite skipped (-SkipTests)"
} else {
    Write-Step "Running test suite (uv run pytest tests/ -v)..."
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $env:PYTHONUNBUFFERED = "1"
    try {
        uv run pytest tests/ -v 2>&1 | ForEach-Object { Write-Host "  $_" }
    } finally {
        $ErrorActionPreference = $prevPref
    }

    $testExit = $LASTEXITCODE
    if ($testExit -ne 0) {
        Write-Host ""
        Write-Warn "Test suite failed (exit code $testExit)."
        Write-Host ""
        $continue = Read-Host "  Continue anyway? (y/N)"
        if ($continue -notin 'y', 'Y') {
            Write-Host "  Aborted." -ForegroundColor Red
            Exit-Script 1
        }
        Write-Warn "Continuing despite test failures."
    } else {
        Write-Ok "All tests passed"
    }
}

} # end test suite (skipped for Install mode)


# ==============================================================================
#  Build helper function (used by Build and Release modes)
# ==============================================================================

function Build-Variant {
    param(
        [Parameter(Mandatory)] [string]$VariantTag,    # 'gpu' or 'cpu'
        [Parameter(Mandatory)] [string]$SpecFile,      # e.g. 'speakeasy.spec'
        [Parameter(Mandatory)] [string]$IssFile,       # e.g. 'installer\speakeasy-setup.iss'
        [Parameter(Mandatory)] [string]$DistDir,       # e.g. 'dist\speakeasy'
        [Parameter(Mandatory)] [string]$HashFilePath,  # e.g. 'build\.speakeasy-build-hash'
        [Parameter(Mandatory)] [string]$InstallerGlob  # e.g. 'SpeakEasy-AI-Granite-Setup-*.exe'
    )

    $distExe = "$DistDir\speakeasy.exe"
    $label = $VariantTag.ToUpper()

    # â”€â”€ Step 1: PyInstaller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if ($InnoOnly) {
        Write-Step "[$label] Skipping PyInstaller (-InnoOnly flag set)"
        if (-not (Test-Path $distExe)) {
            Write-Err "$distExe not found. Run a full build first."
            Exit-Script 1
        }
        Write-Ok "Using existing binary: $distExe"
    } else {
        $skipPyInstaller = $false
        if (-not $Clean) {
            $currentHash = Get-SourceHash -VariantTag $VariantTag
            if ((Test-Path $HashFilePath) -and (Test-Path $distExe)) {
                $savedHash = Get-Content $HashFilePath -Raw
                if ($savedHash.Trim() -eq $currentHash) {
                    $skipPyInstaller = $true
                }
            }
        }

        if ($skipPyInstaller) {
            Write-Step "[$label] PyInstaller skipped (source unchanged since last build)"
            Write-Ok "Using cached binary: $distExe"
        } else {
            # â”€â”€ CPU variant: install CPU-only torch before PyInstaller â”€â”€â”€
            # GPU torch DLLs (shm.dll, torch.dll, torch_python.dll) have
            # hard imports of torch_cuda.dll. Stripping that file from the
            # bundle causes WinError 126 at runtime. CPU torch wheels ship
            # DLLs compiled without any CUDA references.
            $swappedTorch = $false
            if ($VariantTag -eq 'cpu') {
                Write-Step "[$label] Installing CPU-only torch (replacing GPU torch)..."
                $prevPref = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    # --no-deps: only swap torch itself, keep everything else
                    # uv pip returns exit-code 1 (lockfile mismatch) even on
                    # success, so we verify via Python instead of $LASTEXITCODE.
                    uv pip install torch --index-url https://download.pytorch.org/whl/cpu --reinstall-package torch --no-deps 2>&1 |
                        ForEach-Object { Write-Host "  $_" }
                } finally {
                    $ErrorActionPreference = $prevPref
                }
                $cpuCheck = & .venv\Scripts\python.exe -c "import torch; print(torch.__version__)" 2>&1
                if ($cpuCheck -notmatch '\+cpu') {
                    Write-Err "CPU torch installation failed (got: $cpuCheck)."
                    Exit-Script 1
                }
                $swappedTorch = $true
                Write-Ok "CPU torch installed ($cpuCheck)"
            }

            Write-Step "[$label] Building SpeakEasy AI binary with PyInstaller..."

            $pyiArgs = @("pyinstaller", $SpecFile, "--noconfirm")
            if ($Clean) { $pyiArgs += "--clean" }

            $prevPref = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                if ($swappedTorch) {
                    # uv run would re-sync the lockfile (restoring GPU torch),
                    # so invoke PyInstaller directly from the venv.
                    & .venv\Scripts\pyinstaller.exe $SpecFile --noconfirm $(if ($Clean) { '--clean' }) 2>&1 |
                        ForEach-Object { Write-Host "  $_" }
                } else {
                    uv run @pyiArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
                }
            } finally {
                $ErrorActionPreference = $prevPref
            }
            $pyiExit = $LASTEXITCODE

            # â”€â”€ Restore GPU torch after CPU build â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if ($swappedTorch) {
                Write-Step "[$label] Restoring GPU torch..."
                $prevPref = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    uv sync --extra dev 2>&1 | ForEach-Object { Write-Host "  $_" }
                } finally {
                    $ErrorActionPreference = $prevPref
                }
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "Failed to restore GPU torch. Run 'uv sync --extra dev' manually."
                } else {
                    Write-Ok "GPU torch restored"
                }
            }

            if ($pyiExit -ne 0) {
                Write-Err "PyInstaller build failed."
                Exit-Script 1
            }

            if (-not (Test-Path $distExe)) {
                Write-Err "$distExe not found after build."
                Exit-Script 1
            }
            Write-Ok "Binary built: $distExe"

            $currentHash = Get-SourceHash -VariantTag $VariantTag
            if (-not (Test-Path "build")) { New-Item -ItemType Directory -Path "build" | Out-Null }
            $currentHash | Set-Content $HashFilePath -NoNewline
            Write-Ok "Build hash saved"
        }
    }

    # â”€â”€ Step 2: Inno Setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    Write-Step "[$label] Building installer with Inno Setup..."

    Write-Host "  Using: $($iscc)"
    $isccArgs = @($IssFile)
    if ($Fast) {
        $isccArgs = @("/DFastCompress") + $isccArgs
        Write-Host "  Mode: fast compression (dev build)" -ForegroundColor Yellow
    } else {
        Write-Host "  Mode: ultra64 solid compression (release build)"
    }
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $iscc @isccArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Inno Setup compilation failed."
        Exit-Script 1
    }

    $setupExe = Get-ChildItem "installer\Output\$InstallerGlob" | Select-Object -First 1
    if ($setupExe) {
        Write-Ok "Installer built: $($setupExe.FullName)"
        Write-Host ""
        Write-Host "  File size: $([math]::Round($setupExe.Length / 1MB, 1)) MB" -ForegroundColor DarkGray
    } else {
        Write-Warn "Expected output not found in installer\Output\"
    }
}


# ==============================================================================
#  MODE: Build
# ==============================================================================

if ($Mode -eq 'Build') {

    $variantsToBuild = switch ($Variant) {
        'GPU'  { @('gpu') }
        'CPU'  { @('cpu') }
        'Both' { @('gpu', 'cpu') }
    }

    foreach ($v in $variantsToBuild) {
        if ($v -eq 'gpu') {
            Build-Variant `
                -VariantTag  'gpu' `
                -SpecFile    'speakeasy.spec' `
                -IssFile     'installer\speakeasy-setup.iss' `
                -DistDir     'dist\speakeasy' `
                -HashFilePath $HashFile `
                -InstallerGlob 'SpeakEasy-AI-Granite-Setup-*.exe'
        } else {
            Build-Variant `
                -VariantTag  'cpu' `
                -SpecFile    'speakeasy-cpu.spec' `
                -IssFile     'installer\speakeasy-cpu-setup.iss' `
                -DistDir     'dist\speakeasy-cpu' `
                -HashFilePath $CpuHashFile `
                -InstallerGlob 'SpeakEasy-AI-Granite-CPU-Setup-*.exe'
        }
    }

    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host "  Build complete." -ForegroundColor Green
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host ""

    Exit-Script 0
}


# ==============================================================================
#  MODE: Release (build + install + validate + launch)
# ==============================================================================

if ($Mode -eq 'Release') {

    # -- Admin elevation -------------------------------------------------------
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        Write-Warn "Release mode requires admin privileges. Elevating..."
        $scriptPath = $MyInvocation.MyCommand.Path
        $elevateArgs = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', "`"$scriptPath`"",
            '-Mode', 'Release',
            '-Variant', $Variant
        )
        if ($SkipTests) { $elevateArgs += '-SkipTests' }
        if ($Clean)     { $elevateArgs += '-Clean' }
        if ($Fast)      { $elevateArgs += '-Fast' }
        try {
            Start-Process powershell.exe -Verb RunAs -ArgumentList $elevateArgs
        } catch {
            Write-Err "Failed to elevate: $_"
            Exit-Script 1
        }
        Write-Info "Elevated process started. This window can be closed."
        Exit-Script 0
    }

    Write-Ok "Running as Administrator"

    # -- Build installer(s) ----------------------------------------------------
    Write-Step "Building installer(s)..."

    $variantsToBuild = switch ($Variant) {
        'GPU'  { @('gpu') }
        'CPU'  { @('cpu') }
        'Both' { @('gpu', 'cpu') }
    }

    foreach ($v in $variantsToBuild) {
        if ($v -eq 'gpu') {
            Build-Variant `
                -VariantTag  'gpu' `
                -SpecFile    'speakeasy.spec' `
                -IssFile     'installer\speakeasy-setup.iss' `
                -DistDir     'dist\speakeasy' `
                -HashFilePath $HashFile `
                -InstallerGlob 'SpeakEasy-AI-Granite-Setup-*.exe'
        } else {
            Build-Variant `
                -VariantTag  'cpu' `
                -SpecFile    'speakeasy-cpu.spec' `
                -IssFile     'installer\speakeasy-cpu-setup.iss' `
                -DistDir     'dist\speakeasy-cpu' `
                -HashFilePath $CpuHashFile `
                -InstallerGlob 'SpeakEasy-AI-Granite-CPU-Setup-*.exe'
        }
    }
    Write-Ok "Installer(s) built successfully"

    # For install/validate/launch steps, use GPU as the primary variant when Both
    # (both variants share the same Inno Setup AppId -- only one can be installed).
    $installVariant = if ($Variant -eq 'CPU') { 'cpu' } else { 'gpu' }

    # Validate the freshly built frozen bundle now that dist/ reflects the
    # current spec and source tree.
    Write-Step "Validating fresh frozen build (uv run pytest tests/test_frozen_compat.py -v)..."
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        uv run pytest tests/test_frozen_compat.py -v --tb=short 2>&1 | ForEach-Object { Write-Host "  $_" }
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Frozen-build validation failed (exit code $LASTEXITCODE)."
        Exit-Script 1
    }
    Write-Ok "Fresh frozen build validated"

    # -- Silent uninstall ------------------------------------------------------
    Write-Step "Checking for existing SpeakEasy AI installation..."

    $uninstallKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}_is1'
    # Also check WOW6432Node for 32-bit Inno Setup entries
    $uninstallKeyWow = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}_is1'

    $uninstallString = $null
    foreach ($key in @($uninstallKey, $uninstallKeyWow)) {
        if (Test-Path $key) {
            $regEntry = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
            if ($regEntry.UninstallString) {
                $uninstallString = $regEntry.UninstallString
                break
            }
        }
    }

    if ($uninstallString) {
        # Strip any existing quotes from the path
        $uninstallerPath = $uninstallString -replace '"', ''
        Write-Info "Found uninstaller: $uninstallerPath"
        Write-Step "Silently uninstalling old version (models will be preserved)..."

        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $proc = Start-Process -FilePath $uninstallerPath `
                -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' `
                -Wait -PassThru
        } finally {
            $ErrorActionPreference = $prevPref
        }

        if ($proc.ExitCode -ne 0) {
            Write-Warn "Uninstaller exited with code $($proc.ExitCode) (may be okay)."
        } else {
            Write-Ok "Old version uninstalled (models preserved)"
        }
    } else {
        Write-Info "No existing SpeakEasy AI installation found -- skipping uninstall."
    }

    # -- Post-uninstall cleanup (belt-and-suspenders) --------------------------
    # The old embedded uninstaller may lack the cleanup rules added in this
    # version, so explicitly nuke config/logs/temp to guarantee a clean slate.
    # Models are always preserved.
    $installDir = 'C:\Program Files\SpeakEasy AI Granite'
    $dataDir    = "$env:PROGRAMDATA\SpeakEasy AI Granite"
    Write-Step "Cleaning leftover settings/logs/temp from previous install..."
    # Clean old layout (data under Program Files) and new layout (data under ProgramData)
    foreach ($baseDir in @($installDir, $dataDir)) {
        foreach ($sub in @('config', 'logs', 'temp')) {
            $dir = Join-Path $baseDir $sub
            if (Test-Path $dir) {
                Remove-Item $dir -Recurse -Force
                Write-Ok "Removed $dir"
            }
        }
    }

    # -- Silent install --------------------------------------------------------
    Write-Step "Installing new build..."

    $setupPattern = if ($installVariant -eq 'cpu') { 'SpeakEasy-AI-Granite-CPU-Setup-*.exe' } else { 'SpeakEasy-AI-Granite-Setup-*.exe' }
    $setupExe = Get-ChildItem "installer\Output\$setupPattern" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $setupExe) {
        Write-Err "No installer found in installer\Output\. Build may have failed."
        Exit-Script 1
    }

    Write-Info "Installing: $($setupExe.Name) ($([math]::Round($setupExe.Length / 1MB, 1)) MB)"

    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $proc = Start-Process -FilePath $setupExe.FullName `
            -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' `
            -Wait -PassThru
    } finally {
        $ErrorActionPreference = $prevPref
    }

    if ($proc.ExitCode -ne 0) {
        Write-Err "Installer failed (exit code $($proc.ExitCode))."
        Exit-Script 1
    }
    Write-Ok "SpeakEasy AI installed successfully"

    # -- Verify installed bundle matches freshly-built dist --------------------
    $distSubdir = if ($installVariant -eq 'cpu') { 'dist\speakeasy-cpu' } else { 'dist\speakeasy' }
    $distTorchLib = Join-Path $RepoRoot "$distSubdir\_internal\torch\lib"
    $installedTorchLib = 'C:\Program Files\SpeakEasy AI Granite\_internal\torch\lib'
    Write-Step "Verifying installed torch DLL bundle..."

    $distTorchDlls = Get-RelativeFileList $distTorchLib
    $installedTorchDlls = Get-RelativeFileList $installedTorchLib
    $missingTorchDlls = @($distTorchDlls | Where-Object { $_ -notin $installedTorchDlls })

    if ($distTorchDlls.Count -eq 0) {
        Write-Err "Fresh dist torch DLLs not found at $distTorchLib"
        Exit-Script 1
    }
    if (-not (Test-Path $installedTorchLib)) {
        Write-Err "Installed torch DLL directory not found at $installedTorchLib"
        Exit-Script 1
    }
    if ($missingTorchDlls.Count -gt 0) {
        Write-Err "Installed app is missing $($missingTorchDlls.Count) torch DLL(s) from the fresh build."
        $preview = $missingTorchDlls | Select-Object -First 10
        foreach ($name in $preview) {
            Write-Info "Missing: $name"
        }
        if ($missingTorchDlls.Count -gt $preview.Count) {
            Write-Info "...and $($missingTorchDlls.Count - $preview.Count) more"
        }
        Exit-Script 1
    }
    Write-Ok "Installed torch DLL bundle matches dist"

    # -- Verify Granite model is present ---------------------------------------
    $installedGraniteConfig = 'C:\Program Files\SpeakEasy AI Granite\models\granite\config.json'
    if (Test-Path $installedGraniteConfig) {
        Write-Ok "Granite model found at C:\Program Files\SpeakEasy AI Granite\models\granite"
    } else {
        Write-Warn "Granite model NOT found at $installedGraniteConfig"
        Write-Info "The installer may not have downloaded the model."
        Write-Info "The app will prompt for model setup on launch."
    }

    # -- Launch ----------------------------------------------------------------
    Write-Step "Launching SpeakEasy AI Granite (installed build)..."

    $installedExe = 'C:\Program Files\SpeakEasy AI Granite\speakeasy.exe'
    if (-not (Test-Path $installedExe)) {
        Write-Err "speakeasy.exe not found at $installedExe"
        Exit-Script 1
    }

    # Stop any running instance so the new launch does not hit the
    # "Another instance is already running" single-instance guard.
    Get-Process -Name 'speakeasy' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    Start-Process $installedExe
    Write-Ok "SpeakEasy AI launched from $installedExe"

    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host "  Release build test complete." -ForegroundColor Green
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host ""

    Exit-Script 0
}


# ==============================================================================
#  MODE: Install (silently install a pre-built installer)
# ==============================================================================

if ($Mode -eq 'Install') {

    # -- Admin elevation -------------------------------------------------------
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        Write-Warn "Install mode requires admin privileges. Elevating..."
        $scriptPath = $MyInvocation.MyCommand.Path
        $elevateArgs = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', "`"$scriptPath`"",
            '-Mode', 'Install',
            '-Variant', $Variant
        )
        try {
            Start-Process powershell.exe -Verb RunAs -ArgumentList $elevateArgs
        } catch {
            Write-Err "Failed to elevate: $_"
            Exit-Script 1
        }
        Write-Info "Elevated process started. This window can be closed."
        Exit-Script 0
    }

    Write-Ok "Running as Administrator"

    # -- Find installer --------------------------------------------------------
    $setupPattern = if ($Variant -eq 'CPU') { 'SpeakEasy-AI-Granite-CPU-Setup-*.exe' } else { 'SpeakEasy-AI-Granite-Setup-*.exe' }
    $setupExe = Get-ChildItem "installer\Output\$setupPattern" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $setupExe) {
        Write-Err "No $($Variant.ToUpper()) installer found in installer\Output\."
        Write-Info "Run a build first: .\installer\Build-Installer.ps1 -Mode Build -Variant $Variant"
        Exit-Script 1
    }

    Write-Ok "Found installer: $($setupExe.Name) ($([math]::Round($setupExe.Length / 1MB, 1)) MB)"

    # -- Silent uninstall ------------------------------------------------------
    Write-Step "Checking for existing SpeakEasy AI installation..."

    $uninstallKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}_is1'
    $uninstallKeyWow = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{7B99C492-7E14-4E3A-A8F2-71F8B23D9A42}_is1'

    $uninstallString = $null
    foreach ($key in @($uninstallKey, $uninstallKeyWow)) {
        if (Test-Path $key) {
            $regEntry = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
            if ($regEntry.UninstallString) {
                $uninstallString = $regEntry.UninstallString
                break
            }
        }
    }

    if ($uninstallString) {
        $uninstallerPath = $uninstallString -replace '"', ''
        Write-Info "Found uninstaller: $uninstallerPath"
        Write-Step "Silently uninstalling old version (models will be preserved)..."

        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $proc = Start-Process -FilePath $uninstallerPath `
                -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' `
                -Wait -PassThru
        } finally {
            $ErrorActionPreference = $prevPref
        }

        if ($proc.ExitCode -ne 0) {
            Write-Warn "Uninstaller exited with code $($proc.ExitCode) (may be okay)."
        } else {
            Write-Ok "Old version uninstalled (models preserved)"
        }
    } else {
        Write-Info "No existing SpeakEasy AI installation found -- skipping uninstall."
    }

    # -- Post-uninstall cleanup ------------------------------------------------
    $installDir = 'C:\Program Files\SpeakEasy AI Granite'
    Write-Step "Cleaning leftover settings/logs/temp..."
    foreach ($sub in @('config', 'logs', 'temp')) {
        $dir = Join-Path $installDir $sub
        if (Test-Path $dir) {
            Remove-Item $dir -Recurse -Force
            Write-Ok "Removed $dir"
        }
    }

    # -- Silent install --------------------------------------------------------
    Write-Step "Installing $($setupExe.Name)..."

    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $proc = Start-Process -FilePath $setupExe.FullName `
            -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' `
            -Wait -PassThru
    } finally {
        $ErrorActionPreference = $prevPref
    }

    if ($proc.ExitCode -ne 0) {
        Write-Err "Installer failed (exit code $($proc.ExitCode))."
        Exit-Script 1
    }
    Write-Ok "SpeakEasy AI Granite installed successfully"

    # -- Launch ----------------------------------------------------------------
    Write-Step "Launching SpeakEasy AI Granite..."

    $installedExe = 'C:\Program Files\SpeakEasy AI Granite\speakeasy.exe'
    if (-not (Test-Path $installedExe)) {
        Write-Err "speakeasy.exe not found at $installedExe"
        Exit-Script 1
    }

    Get-Process -Name 'speakeasy' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    Start-Process $installedExe
    Write-Ok "SpeakEasy AI launched from $installedExe"

    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host "  Install complete." -ForegroundColor Green
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host ""

    Exit-Script 0
}


# ==============================================================================
#  MODE: Source (run from source, no system changes)
# ==============================================================================

if ($Mode -eq 'Source') {

    $devTemp = Join-Path $RepoRoot 'dev-temp'

    if ($Clean) {
        Write-Step "Cleaning dev-temp state..."
        foreach ($sub in @('config', 'logs', 'temp')) {
            $path = Join-Path $devTemp $sub
            if (Test-Path $path) {
                Remove-Item $path -Recurse -Force
            }
        }
        Write-Ok "dev-temp config/logs/temp reset"
    }

    # -- Set up dev-temp directory ---------------------------------------------
    Write-Step "Setting up dev-temp environment..."

    foreach ($sub in @('config', 'logs', 'temp')) {
        $dir = Join-Path $devTemp $sub
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
    Write-Ok "dev-temp directories ready at $devTemp"

    $settingsPath = Join-Path $devTemp 'config\settings.json'
    if (Test-Path $settingsPath) {
        try {
            $devSettings = Get-Content $settingsPath -Raw | ConvertFrom-Json
            if ($null -ne $devSettings.hotkeys_enabled -and -not $devSettings.hotkeys_enabled) {
                Write-Warn "Global hotkeys are disabled in dev-temp\config\settings.json"
                Write-Info "Enable them in Settings or rerun Source mode with -Clean to reset dev-temp."
            }
        } catch {
            Write-Warn "Could not inspect dev-temp\config\settings.json"
        }
    }

    # -- Model access via directory junction -----------------------------------
    $devModels = Join-Path $devTemp 'models'
    $installedModels = 'C:\Program Files\SpeakEasy AI Granite\models'
    $repoModels = Join-Path $RepoRoot 'models'

    if (Test-Path $devModels) {
        # Already exists (junction or directory from previous run)
        Write-Ok "dev-temp\models already exists"
    } elseif (Test-Path $installedModels) {
        # Create junction to installed models (no admin, no duplication)
        Write-Info "Creating junction: dev-temp\models -> $installedModels"
        cmd /c mklink /J "$devModels" "$installedModels" | Out-Null
        if (Test-Path $devModels) {
            Write-Ok "Junction created to installed models"
        } else {
            Write-Warn "Junction creation failed. Falling back to repo models."
            if (Test-Path $repoModels) {
                cmd /c mklink /J "$devModels" "$repoModels" | Out-Null
            }
        }
    } elseif (Test-Path $repoModels) {
        # No installed models -- link to repo models folder
        Write-Info "No installed models found. Creating junction to repo models."
        cmd /c mklink /J "$devModels" "$repoModels" | Out-Null
        Write-Ok "Junction created to repo models"
    } else {
        Write-Warn "No model files found. The app may prompt you to download models."
    }

    # -- Validate model presence -----------------------------------------------
    $graniteConfig = Join-Path $devModels 'granite\config.json'
    if (Test-Path $graniteConfig) {
        Write-Ok "Granite model found at $devModels\granite"
    } else {
        Write-Warn "Granite model NOT found at $devModels\granite\config.json"
        Write-Info "The app will prompt for model setup on launch."
        Write-Info "To download manually:"
        Write-Info "  uv run python -m speakeasy download-model"
    }

    # -- Launch from source ----------------------------------------------------
    Write-Step "Launching SpeakEasy AI from source..."
    Write-Info "SPEAKEASY_HOME = $devTemp"
    Write-Info "Config, logs, and temp files go to dev-temp/ (not Program Files)."
    Write-Host ""

    $env:SPEAKEASY_HOME = $devTemp

    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        uv run python -m speakeasy 2>&1 | ForEach-Object { Write-Host "  $_" }
    } finally {
        $ErrorActionPreference = $prevPref
    }

    # Clean up env var so it doesn't leak to the rest of the session
    Remove-Item Env:\SPEAKEASY_HOME -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Host "  Source test session ended." -ForegroundColor Green
    Write-Host "  =========================================" -ForegroundColor Green
    Write-Info "dev-temp/ persists between runs. Use -Clean to reset config/logs/temp."
    Write-Host ""

    Exit-Script 0
}

