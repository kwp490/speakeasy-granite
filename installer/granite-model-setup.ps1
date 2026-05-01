# ─────────────────────────────────────────────────────────────────────────────
# IBM Granite Speech Model Setup
#
# This script guides the user through downloading the IBM Granite Speech model
# from HuggingFace. It can be launched standalone to (re)download the model
# after installation.
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
    Write-Host '  IBM Granite Speech — Model Setup' -ForegroundColor Cyan
    Write-Host '════════════════════════════════════════════════════════════════' -ForegroundColor Cyan
    Write-Host ''
}

function Write-Instructions {
    Write-Host 'IBM Granite Speech is downloaded from HuggingFace.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Step 1: Create a free HuggingFace account if needed' -ForegroundColor White
    Write-Host '          https://huggingface.co/join' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Step 2: Review the model page' -ForegroundColor White
    Write-Host '          https://huggingface.co/ibm-granite/granite-speech-4.1-2b' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Step 3: Create an access token if HuggingFace requests one' -ForegroundColor White
    Write-Host '          https://huggingface.co/settings/tokens' -ForegroundColor Green
    Write-Host ''
}

function Start-Download {
    while ($true) {
        Write-Host ''
        $secureToken = Read-Host -AsSecureString 'Paste your HuggingFace access token (press Enter to try anonymous download)'

        if ($secureToken.Length -gt 0) {
            $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
            $env:HF_TOKEN = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }

        Write-Host ''
        Write-Host 'Downloading Granite model — this may take several minutes...' -ForegroundColor Cyan

        try {
            $arguments = @('download-model')
            if ($TargetDir) {
                $arguments += @('--target-dir', "`"$TargetDir`"")
            }

            $tmpOut = [System.IO.Path]::GetTempFileName()
            $tmpErr = [System.IO.Path]::GetTempFileName()

            $process = Start-Process -FilePath $Exe `
                -ArgumentList $arguments `
                -Wait -PassThru -NoNewWindow `
                -RedirectStandardOutput $tmpOut `
                -RedirectStandardError  $tmpErr

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
                Write-Host 'Granite model downloaded successfully!' -ForegroundColor Green
                return 0
            }
            2 {
                Write-Host ''
                Write-Host 'Model access denied.' -ForegroundColor Red
                Write-Host 'Verify your token and access to:' -ForegroundColor Yellow
                Write-Host '  https://huggingface.co/ibm-granite/granite-speech-4.1-2b' -ForegroundColor Green
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

Write-Banner
Write-Instructions
$exitCode = Start-Download

Write-Host ''
Write-Host 'Press any key to close...' -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')

exit $exitCode