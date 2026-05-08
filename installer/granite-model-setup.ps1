# ─────────────────────────────────────────────────────────────────────────────
# IBM Granite Speech Model Setup
#
# This script guides the user through downloading the IBM Granite Speech model
# from HuggingFace. It can be launched standalone to (re)download the model
# after installation.
#
# No HuggingFace account or token is required — ibm-granite/granite-speech-4.1-2b
# is a public model.
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
    Write-Host 'No account or token is required — this is a public model.' -ForegroundColor Gray
    Write-Host ''
    Write-Host '  Model page:' -ForegroundColor White
    Write-Host '  https://huggingface.co/ibm-granite/granite-speech-4.1-2b' -ForegroundColor Green
    Write-Host ''
}

function Write-DownloadOutputLine {
    param(
        [string]$Line,
        [switch]$ErrorLine
    )

    if ([string]::IsNullOrWhiteSpace($Line)) { return }

    $prefix = 'SPEAKEASY_PROGRESS '
    if ($Line.StartsWith($prefix)) {
        try {
            $payload = $Line.Substring($prefix.Length) | ConvertFrom-Json -ErrorAction Stop
            $status = if ($payload.message) { [string]$payload.message } else { 'Downloading Granite model' }
            if ($null -ne $payload.percent) {
                $percent = [Math]::Max(0, [Math]::Min(100, [int]$payload.percent))
                Write-Progress -Activity 'Downloading Granite model' -Status $status -PercentComplete $percent
            } else {
                Write-Progress -Activity 'Downloading Granite model' -Status $status
            }
        } catch {
            Write-Host $Line -ForegroundColor DarkGray
        }
        return
    }

    if ($ErrorLine) {
        Write-Host $Line -ForegroundColor Yellow
    } else {
        Write-Host $Line
    }
}

function Write-ProcessOutput {
    param(
        [string]$StdoutPath,
        [string]$StderrPath,
        [ref]$StdoutIndex,
        [ref]$StderrIndex
    )

    if (Test-Path $StdoutPath) {
        $outLines = @(Get-Content $StdoutPath -ErrorAction SilentlyContinue)
        for ($i = $StdoutIndex.Value; $i -lt $outLines.Count; $i++) {
            Write-DownloadOutputLine -Line $outLines[$i]
        }
        $StdoutIndex.Value = $outLines.Count
    }

    if (Test-Path $StderrPath) {
        $errLines = @(Get-Content $StderrPath -ErrorAction SilentlyContinue)
        for ($i = $StderrIndex.Value; $i -lt $errLines.Count; $i++) {
            Write-DownloadOutputLine -Line $errLines[$i] -ErrorLine
        }
        $StderrIndex.Value = $errLines.Count
    }
}

function Start-Download {
    while ($true) {
        Write-Host ''
        Write-Host 'Downloading Granite model — this may take several minutes...' -ForegroundColor Cyan

        try {
            $arguments = @('download-model', '--progress-format', 'jsonl')
            if ($TargetDir) {
                $arguments += @('--target-dir', "`"$TargetDir`"")
            }

            $tmpOut = [System.IO.Path]::GetTempFileName()
            $tmpErr = [System.IO.Path]::GetTempFileName()

            $process = Start-Process -FilePath $Exe `
                -ArgumentList $arguments `
                -PassThru -NoNewWindow `
                -RedirectStandardOutput $tmpOut `
                -RedirectStandardError  $tmpErr

            $outIndex = 0
            $errIndex = 0
            while (-not $process.HasExited) {
                Write-ProcessOutput $tmpOut $tmpErr ([ref]$outIndex) ([ref]$errIndex)
                Start-Sleep -Milliseconds 250
                $process.Refresh()
            }

            Write-ProcessOutput $tmpOut $tmpErr ([ref]$outIndex) ([ref]$errIndex)
            Write-Progress -Activity 'Downloading Granite model' -Completed
            Remove-Item $tmpOut, $tmpErr -ErrorAction SilentlyContinue
        } catch {
            Write-Progress -Activity 'Downloading Granite model' -Completed
            Write-Host ''
            Write-Host "ERROR: Failed to launch download: $_" -ForegroundColor Red
            Write-Host 'Would you like to try again?' -ForegroundColor White
            $retry = Read-Host '[R]etry or [S]kip? (R/S)'
            if ($retry -ne 'R' -and $retry -ne 'r') {
                Write-Host ''
                Write-Host 'Skipped. You can run this setup later:' -ForegroundColor Yellow
                Write-Host "  & '$Exe' download-model" -ForegroundColor Gray
                return 1
            }
            continue
        }

        switch ($process.ExitCode) {
            0 {
                Write-Host ''
                Write-Host 'Granite model downloaded successfully!' -ForegroundColor Green
                return 0
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
            Write-Host "  & '$Exe' download-model" -ForegroundColor Gray
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