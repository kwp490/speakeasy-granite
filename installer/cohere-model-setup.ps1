# ─────────────────────────────────────────────────────────────────────────────
# Cohere Transcribe Model Setup
#
# This script guides the user through downloading the Cohere Transcribe
# model from HuggingFace.  It can be launched standalone to (re)download
# the model after installation.
#
# The HuggingFace token is used for this single download only.
# It is NOT stored anywhere — not in settings or on disk.
# It is briefly set as the HF_TOKEN environment variable so the child
# process can inherit it without the token appearing on the command line.
# The variable is cleared immediately after the download completes.
# ─────────────────────────────────────────────────────────────────────────────

param(
    [string]$TargetDir = ''
)

$ErrorActionPreference = 'Stop'

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Exe    = Join-Path $AppDir 'speakeasy.exe'

if (-not (Test-Path $Exe)) {
    Write-Host ''
    Write-Host 'ERROR: speakeasy.exe not found at:' -ForegroundColor Red
    Write-Host "  $Exe" -ForegroundColor Red
    Write-Host ''
    Write-Host 'This script is designed for the installed build.' -ForegroundColor Yellow
    Write-Host 'If running from source, the app handles downloads directly.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'Press any key to close...' -ForegroundColor Gray
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    exit 1
}

function Write-Banner {
    Write-Host ''
    Write-Host '════════════════════════════════════════════════════════════════' -ForegroundColor Cyan
    Write-Host '  Cohere Transcribe — Model Setup' -ForegroundColor Cyan
    Write-Host '════════════════════════════════════════════════════════════════' -ForegroundColor Cyan
    Write-Host ''
}

function Write-Instructions {
    Write-Host 'Cohere Transcribe requires a free HuggingFace account.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Step 1: Create a free account at' -ForegroundColor White
    Write-Host '          https://huggingface.co/join' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Step 2: Go to the model page and click "Agree and access repository"' -ForegroundColor White
    Write-Host '          https://huggingface.co/CohereLabs/cohere-transcribe-03-2026' -ForegroundColor Green
    Write-Host '          (use the same account the token belongs to)' -ForegroundColor Gray
    Write-Host ''
    Write-Host '  Step 3: Create an access token (Read permission is sufficient)' -ForegroundColor White
    Write-Host '          https://huggingface.co/settings/tokens' -ForegroundColor Green
    Write-Host ''
}

function Start-Download {
    while ($true) {
        Write-Host ''
        $secureToken = Read-Host -AsSecureString 'Paste your HuggingFace access token (press Enter to skip)'

        if ($secureToken.Length -eq 0) {
            Write-Host ''
            Write-Host 'Skipped. You can run this setup later:' -ForegroundColor Yellow
            Write-Host "  `$env:HF_TOKEN = 'your_token'; & '$Exe' download-model" -ForegroundColor Gray
            return 1
        }

        # Extract to plain text only for the child process lifetime, then clear.
        # The token is passed via environment variable, not on the command line,
        # so it does not appear in the Windows process list.
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
        $env:HF_TOKEN = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

        Write-Host ''
        Write-Host 'Downloading Cohere model — this may take several minutes...' -ForegroundColor Cyan

        try {
            $arguments = @('download-model')
            if ($TargetDir) {
                $arguments += @('--target-dir', "`"$TargetDir`"")
            }

            # speakeasy.exe is a GUI-subsystem app (console=False) so stdout/stderr
            # are not inherited from the parent console. Redirect them to temp files
            # so we can display progress and error details.
            $tmpOut = [System.IO.Path]::GetTempFileName()
            $tmpErr = [System.IO.Path]::GetTempFileName()

            $process = Start-Process -FilePath $Exe `
                -ArgumentList $arguments `
                -Wait -PassThru -NoNewWindow `
                -RedirectStandardOutput $tmpOut `
                -RedirectStandardError  $tmpErr

            # Print captured output to the console
            $outLines = Get-Content $tmpOut -ErrorAction SilentlyContinue
            $errLines = Get-Content $tmpErr -ErrorAction SilentlyContinue
            Remove-Item $tmpOut, $tmpErr -ErrorAction SilentlyContinue

            foreach ($line in $outLines) { Write-Host $line }
            foreach ($line in $errLines) { Write-Host $line -ForegroundColor Yellow }
        } catch {
            Write-Host ''
            Write-Host "ERROR: Failed to launch download: $_" -ForegroundColor Red
            Write-Host 'Would you like to try again?' -ForegroundColor White
            $retry = Read-Host '[R]etry or [S]kip? (R/S)'
            if ($retry -ne 'R' -and $retry -ne 'r') {
                Write-Host ''
                Write-Host 'Skipped. You can run this setup later:' -ForegroundColor Yellow
                Write-Host "  `$env:HF_TOKEN = 'your_token'; & '$Exe' download-model" -ForegroundColor Gray
                return 1
            }
            continue
        } finally {
            $env:HF_TOKEN = $null
        }

        switch ($process.ExitCode) {
            0 {
                Write-Host ''
                Write-Host 'Cohere model downloaded successfully!' -ForegroundColor Green
                return 0
            }
            2 {
                Write-Host ''
                Write-Host 'Model access denied.' -ForegroundColor Red
                Write-Host 'Possible causes:' -ForegroundColor Yellow
                Write-Host '  - The token belongs to a different account than the one that' -ForegroundColor Yellow
                Write-Host '    accepted the license (must be the same HuggingFace account)' -ForegroundColor Yellow
                Write-Host '  - Invalid, expired, or revoked token' -ForegroundColor Yellow
                Write-Host '  - You have not yet accepted the license at:' -ForegroundColor Yellow
                Write-Host '    https://huggingface.co/CohereLabs/cohere-transcribe-03-2026' -ForegroundColor Green
                Write-Host ''
                Write-Host 'Would you like to try again?' -ForegroundColor White
            }
            default {
                Write-Host ''
                Write-Host "Download failed (exit code $($process.ExitCode))." -ForegroundColor Red
                Write-Host 'This may be a network error. Would you like to try again?' -ForegroundColor White
            }
        }

        $retry = Read-Host '[R]etry or [S]kip? (R/S)'
        if ($retry -ne 'R' -and $retry -ne 'r') {
            Write-Host ''
            Write-Host 'Skipped. You can run this setup later:' -ForegroundColor Yellow
            Write-Host "  `$env:HF_TOKEN = 'your_token'; & '$Exe' download-model" -ForegroundColor Gray
            return 1
        }
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

Write-Banner
Write-Instructions
$exitCode = Start-Download

Write-Host ''
Write-Host 'Press any key to close...' -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')

exit $exitCode
