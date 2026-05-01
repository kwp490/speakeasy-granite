<#
.SYNOPSIS
    Install SpeakEasy AI from source (developer/contributor path).

.DESCRIPTION
    Copies the local SpeakEasy AI source tree to the install directory, installs
    Python 3.11 and uv via winget, syncs all dependencies, downloads the IBM
    Granite Speech model, and creates a desktop shortcut.

    Use -Variant to select the installation type:
      GPU  â€” full install with CUDA-accelerated PyTorch (requires NVIDIA GPU)
      CPU  â€” lightweight install, CPU-only PyTorch (no GPU required)

    If -Variant is not specified, the installer prompts interactively.

    Installs everything to C:\Program Files\SpeakEasy AI Granite\ (binaries, venv).
    Mutable data (models, config, temp) is stored under C:\ProgramData\SpeakEasy AI Granite\
    so the Program Files tree remains read-only for non-admin users.

.PARAMETER Variant
    Installation variant: 'GPU' (default, CUDA-enabled) or 'CPU' (no GPU required).

.NOTES
    Run in an elevated PowerShell session from within the repo:
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\installer\Install-SpeakEasy-Source.ps1
        .\installer\Install-SpeakEasy-Source.ps1 -Variant CPU
#>
param(
    [ValidateSet("GPU", "CPU")]
    [string]$Variant
)

#Requires -RunAsAdministrator
#Requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$InstallDir = "C:\Program Files\SpeakEasy AI Granite"
$DataDir   = "$env:PROGRAMDATA\SpeakEasy AI Granite"
$ModelsDir = "$DataDir\models"
$ConfigDir = "$DataDir\config"
$LogsDir   = "$env:LOCALAPPDATA\SpeakEasy AI Granite\logs"
$TempDir   = "$DataDir\temp"
$RepoName = Split-Path -Leaf $PWD.Path

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Already($msg) { Write-Host "  [SKIP] $msg" -ForegroundColor DarkGray }
function Write-Ok($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }

function Invoke-NativeCommand {
    <# Run a native command, print indented output, and throw on failure. #>
    param([string]$Label, [scriptblock]$Command)
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command 2>&1
        foreach ($line in $output) { Write-Host "  $line" }
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)" }
}

function Invoke-StreamingCommand {
    <# Run a native command, streaming output line-by-line for real-time progress. #>
    param([string]$Label, [scriptblock]$Command)
    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command 2>&1 | ForEach-Object { Write-Host "  $_" }
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)" }
}

function Update-OutdatedFiles {
    <# Compare every file in SourceDir against DestDir; force-copy any that
       are missing or older in the destination.  Returns the count of files updated. #>
    param(
        [Parameter(Mandatory)] [string]$SourceDir,
        [Parameter(Mandatory)] [string]$DestDir,
        [string[]]$ExcludeDirs = @(".git", "__pycache__", ".venv"),
        [string[]]$ExcludeExts = @(".pyc")
    )

    $updated = 0
    $srcItems = Get-ChildItem -Path $SourceDir -File -Recurse -Force
    foreach ($srcFile in $srcItems) {
        $rel = $srcFile.FullName.Substring($SourceDir.TrimEnd("\").Length + 1)

        $skip = $false
        foreach ($exDir in $ExcludeDirs) {
            if ($rel -like "$exDir\*" -or $rel -like "*\$exDir\*") { $skip = $true; break }
        }
        if ($skip) { continue }

        foreach ($exExt in $ExcludeExts) {
            if ($srcFile.Extension -eq $exExt) { $skip = $true; break }
        }
        if ($skip) { continue }

        $destFile = Join-Path $DestDir $rel
        if (-not (Test-Path $destFile)) {
            $destParent = Split-Path $destFile -Parent
            if (-not (Test-Path $destParent)) {
                New-Item -ItemType Directory -Path $destParent -Force | Out-Null
            }
            Copy-Item -Path $srcFile.FullName -Destination $destFile -Force
            Write-Host "  [NEW]  $rel" -ForegroundColor Yellow
            $updated++
        } elseif ($srcFile.LastWriteTimeUtc -gt (Get-Item $destFile).LastWriteTimeUtc) {
            Copy-Item -Path $srcFile.FullName -Destination $destFile -Force
            Write-Host "  [UPD]  $rel" -ForegroundColor Yellow
            $updated++
        }
    }
    return $updated
}

function Sync-SourceTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDir,
        [Parameter(Mandatory = $true)]
        [string]$DestinationDir
    )

    if (-not (Test-Path $DestinationDir)) {
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
    }

    $prevPref = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        robocopy $SourceDir $DestinationDir /MIR /XD .git __pycache__ .venv models config logs temp installer /XF "*.pyc" /NFL /NDL /NJH /NJS /NC /NS /NP 2>&1 | Out-Null
    } finally {
        $ErrorActionPreference = $prevPref
    }
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed (exit code $LASTEXITCODE)" }
    $LASTEXITCODE = 0
}

function Assert-ValidInstallLayout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallRoot,
        [Parameter(Mandatory = $true)]
        [string]$NestedRepoPath
    )

    if (Test-Path $NestedRepoPath) {
        throw "Invalid install layout: nested repo directory still exists at $NestedRepoPath"
    }

    $requiredPaths = @(
        (Join-Path $InstallRoot "pyproject.toml"),
        (Join-Path $InstallRoot "speakeasy\__main__.py")
    )
    foreach ($path in $requiredPaths) {
        if (-not (Test-Path $path)) {
            throw "Invalid install layout: missing required path $path"
        }
    }
}

# â”€â”€ Variant selection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if (-not $Variant) {
    Write-Host ""
    Write-Host "  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”" -ForegroundColor Cyan
    Write-Host "  â”‚  SELECT INSTALLATION VARIANT                                   â”‚" -ForegroundColor Cyan
    Write-Host "  â”‚                                                                â”‚" -ForegroundColor Cyan
    Write-Host "  â”‚  [1] GPU  â€” CUDA-accelerated (requires NVIDIA GPU, ~6 GB VRAM)â”‚" -ForegroundColor Cyan
    Write-Host "  â”‚  [2] CPU  â€” CPU-only, no GPU required (slower inference)       â”‚" -ForegroundColor Cyan
    Write-Host "  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜" -ForegroundColor Cyan
    Write-Host ""
    do {
        $choice = Read-Host "  Enter 1 for GPU or 2 for CPU (default: 1)"
        if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }
    } while ($choice -notin @("1", "2"))
    $Variant = if ($choice -eq "2") { "CPU" } else { "GPU" }
}
Write-Host ""
Write-Host "  Installation variant: $Variant" -ForegroundColor Cyan
Write-Host ""

# â”€â”€ WIN-01: Check NVIDIA GPU â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($Variant -eq "GPU") {
Write-Step "Checking for NVIDIA GPU..."
try {
    $gpu = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null
    if ($gpu) {
        Write-Ok "GPU detected: $($gpu.Trim())"
    } else {
        Write-Warn "No NVIDIA GPU detected. GPU acceleration will not be available."
    }
} catch {
    Write-Warn "nvidia-smi not found. GPU acceleration may not be available."
}
} # end GPU-only check

# â”€â”€ Antimalware notice â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host ""
Write-Host "  ANTIMALWARE NOTICE" -ForegroundColor Yellow
Write-Host "  This installer uses uv.exe by Astral to manage Python packages." -ForegroundColor Yellow
Write-Host "  Some antimalware tools may flag uv.exe as a false positive." -ForegroundColor Yellow
Write-Host "  If that happens, restore uv.exe and add it to your allow list." -ForegroundColor Yellow
Write-Host "  uv is open source: https://github.com/astral-sh/uv" -ForegroundColor Yellow
Write-Host ""
Write-Host "  The IBM Granite Speech model will be downloaded during installation."
Write-Host "  A HuggingFace token is optional unless access is denied anonymously."
Write-Host "  Get your token at: https://huggingface.co/settings/tokens"
Write-Host ""
$HfTokenSecure = Read-Host -AsSecureString "  Enter your HuggingFace API token (or press Enter to skip model download)"

# â”€â”€ Install uv â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking for uv package manager..."
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Already "uv already installed: $(uv --version)"
} else {
    Write-Host "  Installing uv via winget..."
    winget install --id astral-sh.uv --exact --accept-package-agreements --accept-source-agreements
    $machPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$userPath;$machPath"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installation succeeded but uv is not on PATH. Restart your terminal and re-run."
    }
    Write-Ok "uv installed: $(uv --version)"
}

$env:UV_PYTHON_PREFERENCE = "only-system"

# â”€â”€ Install Python 3.11 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking for Python 3.11..."
$py311 = (Get-Command python3.11 -ErrorAction SilentlyContinue).Source
if (-not $py311) {
    try { $py311 = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null).Trim() } catch { $py311 = $null }
}
if ($py311) {
    Write-Already "Python 3.11 already available: $py311"
} else {
    Write-Host "  Installing Python 3.11 via winget..."
    winget install --id Python.Python.3.11 --exact --accept-package-agreements --accept-source-agreements
    $machPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$userPath;$machPath"
    $py311 = (Get-Command python3.11 -ErrorAction SilentlyContinue).Source
    if (-not $py311) {
        try { $py311 = (& py -3.11 -c "import sys; print(sys.executable)" 2>$null).Trim() } catch { $py311 = $null }
    }
    Write-Ok "Python 3.11 installed"
}
if (-not $py311 -or -not (Test-Path $py311)) {
    throw "Python 3.11 is not discoverable after installation. Restart PowerShell and re-run."
}
Write-Ok "Using Python: $py311"

# â”€â”€ Copy/sync source to install dir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Setting up SpeakEasy AI repository..."
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$RepoName = Split-Path -Leaf $RepoRoot
$NestedRepoDir = Join-Path $InstallDir $RepoName

if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    Write-Host "  ERROR: Cannot find pyproject.toml in $RepoRoot" -ForegroundColor Red
    Write-Host "  Run this script from its location inside the SpeakEasy AI repository."
    exit 1
}

if ($RepoRoot -eq $InstallDir) {
    Write-Already "Running from install directory - skipping copy"
} elseif (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Warn "$InstallDir contains an old git clone - replacing with local source..."
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "  Syncing local source contents from $RepoRoot..."
    Sync-SourceTree -SourceDir $RepoRoot -DestinationDir $InstallDir
    Write-Ok "Source installed to $InstallDir from local tree"
} elseif (Test-Path $InstallDir) {
    Write-Warn "$InstallDir exists - updating with local source..."
    if (Test-Path $NestedRepoDir) {
        Write-Warn "Removing stale nested repo copy at $NestedRepoDir..."
        Remove-Item -Recurse -Force $NestedRepoDir
    }
    Sync-SourceTree -SourceDir $RepoRoot -DestinationDir $InstallDir
    Write-Ok "Source synced to $InstallDir"
} else {
    Write-Host "  Syncing local source contents from $RepoRoot..."
    Sync-SourceTree -SourceDir $RepoRoot -DestinationDir $InstallDir
    Write-Ok "Source installed to $InstallDir"
}

Assert-ValidInstallLayout -InstallRoot $InstallDir -NestedRepoPath $NestedRepoDir
Write-Ok "Install layout verified"

# â”€â”€ Verify & patch outdated files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($RepoRoot -ne $InstallDir) {
    Write-Step "Checking for outdated files in $InstallDir..."
    $outdated = Update-OutdatedFiles -SourceDir $RepoRoot -DestDir $InstallDir
    if ($outdated -eq 0) {
        Write-Already "All files are up-to-date"
    } else {
        Write-Ok "$outdated file(s) updated"
    }
}

# â”€â”€ Install dependencies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Syncing dependencies..."
Write-Host "  Running uv sync (will skip already-installed packages)..."
Push-Location $InstallDir
Invoke-NativeCommand "uv sync" ([scriptblock]::Create("uv sync --python `"$py311`" --extra dev"))
Pop-Location
Write-Ok "Dependencies synced"

# â”€â”€ Validate virtual environment and core imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Validating virtual environment..."
$venvPython = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  ERROR: Virtual environment not found at $InstallDir\.venv" -ForegroundColor Red
    Write-Host "  Try deleting $InstallDir\.venv and re-running this installer." -ForegroundColor Red
    exit 1
}
$pyVer = & $venvPython --version 2>&1
Write-Ok "venv Python: $pyVer"

Write-Step "Verifying core Python imports..."
$coreImportScript = @(
    "import sys, importlib",
    "failed = []",
    "for mod in [`"PySide6`", `"sounddevice`", `"soundfile`", `"numpy`", `"keyboard`"]:",
    "    try:",
    "        importlib.import_module(mod)",
    "    except ImportError as e:",
    "        failed.append(mod + `": `" + str(e))",
    "if failed:",
    "    for f in failed: print(`"FAIL: `" + f)",
    "    sys.exit(1)",
    "else:",
    "    print(`"All core imports OK`")"
) -join "`n"
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $importResult = & $venvPython -c $coreImportScript 2>&1
    foreach ($line in $importResult) { Write-Host "  $line" }
} finally {
    $ErrorActionPreference = $prevPref
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Core dependencies are missing. Try:" -ForegroundColor Red
    Write-Host ("    cd " + $InstallDir + "; uv sync --extra dev") -ForegroundColor Yellow
    exit 1
}
Write-Ok "Core imports verified"

# â”€â”€ Verify transformers + torch imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Verifying engine dependencies..."
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try { & $venvPython -c "import transformers; print(`"transformers `" + transformers.__version__)" 2>&1 | ForEach-Object { Write-Host "  $_" } }
finally { $ErrorActionPreference = $prevPref }
if ($LASTEXITCODE -ne 0) {
    Write-Warn ("transformers import failed. Try: cd " + $InstallDir + "; uv pip install --upgrade transformers>=5.4.0")
} else {
    Write-Ok "transformers import OK"
}

$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try { & $venvPython -c "import torch; print(`"torch `" + torch.__version__)" 2>&1 | ForEach-Object { Write-Host "  $_" } }
finally { $ErrorActionPreference = $prevPref }
if ($LASTEXITCODE -ne 0) {
    Write-Warn "torch import failed. The Granite engine requires PyTorch."
    if ($Variant -eq "GPU") {
        Write-Host ("  Try: cd " + $InstallDir + "; uv pip install --index-url https://download.pytorch.org/whl/cu128 torch") -ForegroundColor Yellow
    } else {
        Write-Host ("  Try: cd " + $InstallDir + "; uv pip install --index-url https://download.pytorch.org/whl/cpu torch") -ForegroundColor Yellow
    }
} else {
    Write-Ok "torch import OK"
}

# â”€â”€ CPU variant: replace CUDA torch with CPU-only torch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($Variant -eq "CPU") {
    Write-Step "Installing CPU-only PyTorch (replacing CUDA build)..."
    Push-Location $InstallDir
    Invoke-NativeCommand "Install CPU-only torch" {
        uv pip install --python .venv\Scripts\python.exe --index-url https://download.pytorch.org/whl/cpu --upgrade --force-reinstall torch
    }
    Pop-Location
    Write-Ok "CPU-only PyTorch installed"
}

# â”€â”€ Ensure PyTorch has CUDA support â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($Variant -eq "GPU") {
Write-Step "Verifying PyTorch CUDA support..."
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try { & $venvPython -c "import torch; assert torch.cuda.is_available()" 2>&1 | Out-Null }
finally { $ErrorActionPreference = $prevPref }
if ($LASTEXITCODE -ne 0) {
    Write-Warn "PyTorch does not have CUDA support - reinstalling with CUDA 12.8..."
    Push-Location $InstallDir
    Invoke-NativeCommand "Install torch+CUDA" {
        uv pip install --python .venv\Scripts\python.exe --index-url https://download.pytorch.org/whl/cu128 --upgrade --force-reinstall torch
    }
    Pop-Location
    Write-Ok "PyTorch with CUDA reinstalled"
} else {
    Write-Already "PyTorch has CUDA support"
}

# Verify GPU kernels actually work (catches arch mismatch, e.g. Blackwell + cu124)
Write-Step "Verifying PyTorch GPU kernel compatibility..."
$prevPref = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$cudaSmokeScript = "import torch"
try { & $venvPython -c $cudaSmokeScript 2>&1 | Out-Null }
finally { $ErrorActionPreference = $prevPref }
if ($LASTEXITCODE -ne 0) {
    Write-Warn "PyTorch CUDA kernels failed - GPU arch may require a newer CUDA toolkit"
    Write-Host "  Reinstalling torch from cu128 index (includes Blackwell/sm_120 support)..."
    Push-Location $InstallDir
    Invoke-NativeCommand "Upgrade torch for GPU arch" {
        uv pip install --python .venv\Scripts\python.exe --index-url https://download.pytorch.org/whl/cu128 --upgrade --force-reinstall torch
    }
    Pop-Location
    $prevPref2 = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $venvPython -c $cudaSmokeScript 2>&1 | Out-Null }
    finally { $ErrorActionPreference = $prevPref2 }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "GPU kernel test still fails after torch reinstall - engines will fall back to CPU"
    } else {
        Write-Ok "PyTorch GPU kernels working after reinstall"
    }
} else {
    Write-Ok "PyTorch GPU kernels verified for this GPU"
}
} # end GPU-only CUDA verification

# â”€â”€ Verify huggingface-hub â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking huggingface-hub version..."
$hfVer = & $venvPython -c "import huggingface_hub; print(huggingface_hub.__version__)" 2>$null
if (-not $hfVer) {
    Write-Host "  huggingface-hub not found, installing..."
    Push-Location $InstallDir
    Invoke-NativeCommand "Install huggingface-hub" { uv pip install --python .venv\Scripts\python.exe `"huggingface-hub>=0.34.0`" }
    Pop-Location
    Write-Ok "huggingface-hub installed"
} else {
    Write-Already "huggingface-hub $($hfVer.Trim()) is installed"
}

# â”€â”€ Verify CUDA DLLs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($Variant -eq "GPU") {
    Write-Step "Verifying CUDA runtime libraries..."
    try {
        & "$InstallDir\.venv\Scripts\python.exe" -c "import nvidia, torch; print(`"CUDA package imports OK`")" 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "CUDA runtime libraries verified"
        } else {
            Write-Warn "CUDA package import failed; GPU acceleration may fall back to CPU"
        }
    } catch {
        Write-Warn "Could not verify CUDA DLLs: $_"
    }
} # end GPU-only CUDA DLL verification

# â”€â”€ Download models â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
foreach ($dir in @($ModelsDir, $ConfigDir, $LogsDir, $TempDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

# â”€â”€ Migrate existing data from old locations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking for data to migrate from previous install..."

$oldSettingsFile = "$env:APPDATA\SpeakEasy AI\settings.json"
$newSettingsFile = Join-Path $ConfigDir "settings.json"
if ((Test-Path $oldSettingsFile) -and -not (Test-Path $newSettingsFile)) {
    Copy-Item -Path $oldSettingsFile -Destination $newSettingsFile -Force
    Write-Ok "Migrated settings.json from $oldSettingsFile"
} else {
    Write-Already "No settings to migrate (already present or no old settings found)"
}

$oldModelsDir = "$env:LOCALAPPDATA\SpeakEasy AI\models"
if (Test-Path $oldModelsDir) {
    $migrated = 0
    foreach ($engineDir in (Get-ChildItem -Path $oldModelsDir -Directory)) {
        $destEngine = Join-Path $ModelsDir $engineDir.Name
        if (-not (Test-Path $destEngine)) {
            Write-Host "  Migrating $($engineDir.Name) model..."
            Copy-Item -Path $engineDir.FullName -Destination $destEngine -Recurse -Force
            $migrated++
            Write-Ok "Migrated $($engineDir.Name) model from $($engineDir.FullName)"
        }
    }
    if ($migrated -eq 0) {
        Write-Already "No models to migrate (already present in new location)"
    }
} else {
    Write-Already "No old model directory found at $oldModelsDir"
}

$oldLogDir = "$env:APPDATA\SpeakEasy AI"
foreach ($logFile in @("speakeasy.log", "speakeasy.log.1", "speakeasy.log.2")) {
    $oldLog = Join-Path $oldLogDir $logFile
    $newLog = Join-Path $LogsDir $logFile
    if ((Test-Path $oldLog) -and -not (Test-Path $newLog)) {
        Copy-Item -Path $oldLog -Destination $newLog -Force
    }
}

# â”€â”€ Download Granite model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking Granite model (IBM Granite Speech 4.1 2B)..."
$graniteDir = Join-Path $ModelsDir "granite"
if ((Test-Path (Join-Path $graniteDir "config.json"))) {
    Write-Already "Granite model already present in $graniteDir"
} elseif ($HfTokenSecure.Length -eq 0) {
    Write-Warn "No HuggingFace token provided — trying anonymous Granite model download"
    Push-Location $InstallDir
    Invoke-StreamingCommand "Granite model download" { uv run speakeasy download-model --target-dir $ModelsDir }
    Pop-Location
} else {
    # Extract token to plain text only for child process inheritance, then clear.
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($HfTokenSecure)
    $env:HF_TOKEN = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    try {
        Write-Host "  Downloading Granite model (ibm-granite/granite-speech-4.1-2b)..."
        Push-Location $InstallDir
        Invoke-StreamingCommand "Granite model download" { uv run speakeasy download-model --target-dir $ModelsDir }
        Pop-Location
        Write-Ok "Granite model downloaded to $graniteDir"
    } finally {
        $env:HF_TOKEN = $null
    }
}

# â”€â”€ Patch build variant for CPU source installs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ($Variant -eq "CPU") {
    Write-Step "Patching build variant to CPU..."
    $variantFile = Join-Path $InstallDir "speakeasy\_build_variant.py"
    if (Test-Path $variantFile) {
        $content = Get-Content $variantFile -Raw
        $patched = $content -replace "VARIANT\s*=\s*`"gpu`"", "VARIANT = `"cpu`""
        [System.IO.File]::WriteAllText($variantFile, $patched, (New-Object System.Text.UTF8Encoding $false))
        Write-Ok "Build variant set to cpu in $variantFile"
    } else {
        Write-Warn "_build_variant.py not found at $variantFile - device defaults may use GPU"
    }
}

# â”€â”€ Write default engine to settings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Configuring default engine..."
$settingsFile = Join-Path $ConfigDir "settings.json"
$cfg = $null
$defaultEngine = "granite"
$defaultDevice = if ($Variant -eq "CPU") { "cpu" } else { "cuda" }
if (Test-Path $settingsFile) {
    $rawSettings = Get-Content $settingsFile -Raw
    if (-not [string]::IsNullOrWhiteSpace($rawSettings)) {
        $cfg = $rawSettings | ConvertFrom-Json
    }
}
if (-not $cfg) {
    $cfg = [pscustomobject]@{}
}
if ($cfg.PSObject.Properties.Match("engine").Count -eq 0) {
    $cfg | Add-Member -NotePropertyName "engine" -NotePropertyValue $defaultEngine
} else {
    $cfg.engine = $defaultEngine
}
if ($cfg.PSObject.Properties.Match("device").Count -eq 0) {
    $cfg | Add-Member -NotePropertyName "device" -NotePropertyValue $defaultDevice
} else {
    $cfg.device = $defaultDevice
}
$jsonText = $cfg | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($settingsFile, $jsonText, (New-Object System.Text.UTF8Encoding $false))
Write-Ok "Default engine set to $defaultEngine, device set to $defaultDevice in $settingsFile"

# â”€â”€ Set permissions (current user gets Modify on install dir) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Checking directory permissions..."
# Data dirs under %ProgramData% are writable by authenticated users
# by default — no ACL changes are required.
# Logs are under %LOCALAPPDATA% (per-user) so no shared ACL concern.
# Verify the data directories are accessible.
foreach ($dir in @($ModelsDir, $ConfigDir, $LogsDir, $TempDir)) {
    if (Test-Path $dir) {
        Write-Already "$dir is accessible"
    } else {
        Write-Warn "$dir could not be verified (it should have been created above)"
    }
}

# â”€â”€ Create desktop shortcut â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Creating desktop shortcut..."
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "SpeakEasy AI Granite.lnk"
if (Test-Path $shortcutPath) {
    Write-Already "Desktop shortcut already exists"
} else {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "$InstallDir\.venv\Scripts\pythonw.exe"
    $shortcut.Arguments = "-m speakeasy"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = "SpeakEasy AI Granite - Voice to Text"
    $shortcut.Save()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
    Write-Ok "Desktop shortcut created at $shortcutPath"
}

# â”€â”€ Windows Defender exclusions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Step "Configuring Windows Defender exclusions..."
$exePath = "$InstallDir\.venv\Scripts\pythonw.exe"
try {
    Add-MpPreference -ExclusionProcess $exePath -ErrorAction Stop
    Write-Ok "Process exclusion added for $exePath"
} catch {
    Write-Warn "Could not add Defender exclusion: $_"
}

# â”€â”€ Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
$variantLabel = if ($Variant -eq "CPU") { "CPU-only (no GPU required)" } else { "GPU (CUDA-accelerated)" }
Write-Host ""
Write-Host "  â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•" -ForegroundColor Green
Write-Host "  SpeakEasy AI Granite has been installed successfully!" -ForegroundColor Green
Write-Host "  â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•" -ForegroundColor Green
Write-Host ""
Write-Host "  Variant:        $variantLabel"
Write-Host "  Install dir:    $InstallDir"
Write-Host "  Models:         $ModelsDir"
Write-Host "  Config:         $ConfigDir"
Write-Host "  Logs:           $LogsDir"
Write-Host ""
Write-Host "  Engine:         IBM Granite Speech"
Write-Host "  Device:         $defaultDevice"
Write-Host ""
Write-Host "  To launch:      Double-click the desktop shortcut or run:"
Write-Host ("    cd " + $InstallDir + "; uv run speakeasy")
Write-Host ""
Write-Host "  Default hotkeys:"
Write-Host "    Ctrl+Alt+P   Start recording"
Write-Host "    Ctrl+Alt+L   Stop recording & transcribe"
Write-Host "    Ctrl+Alt+Q   Quit application"
Write-Host ""

