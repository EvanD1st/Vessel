param(
    [string]$Origin = 'http://localhost:3000',
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
$vesselRoot = Split-Path -Parent $PSScriptRoot
$vesselInterpreter = Join-Path $vesselRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vesselInterpreter)) {
    throw 'Run .\scripts\setup.ps1 first.'
}

Push-Location $vesselRoot
try {
    Write-Host 'Preparing a fresh disposable demo. Cline events are synthetic; no inference request is sent.'
    $demoOutput = & $vesselInterpreter scripts/demo.py
    if ($LASTEXITCODE -ne 0) { throw 'The local recovery demo failed; inspect its error above.' }
    $demoReport = ($demoOutput -join [Environment]::NewLine) | ConvertFrom-Json
    $demoRoot = $demoReport.output_directory
    if (-not $demoRoot -or $demoReport.recovery_status -ne 'succeeded' -or -not $demoReport.backup_restore_verified) {
        throw 'Demo output did not confirm successful recovery and verified backup.'
    }
    $demoState = Join-Path $demoRoot 'private-state'
    Write-Host "Demo report: $(Join-Path $demoRoot 'report.json')"
    Write-Host "Private state: $demoState"
    if (-not $PrepareOnly) {
        Write-Host 'Keep this terminal open. Paste the printed private link into Connect a companion. Ctrl+C stops the bridge.'
        & $vesselInterpreter -m vessel --state $demoState dashboard --origin $Origin --port $Port
        if ($LASTEXITCODE -ne 0) { throw 'Companion bridge stopped with an error.' }
    }
} finally {
    Pop-Location
}
