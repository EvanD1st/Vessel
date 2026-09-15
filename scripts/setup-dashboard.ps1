param([switch]$Reinstall)
$ErrorActionPreference = 'Stop'
$vesselRoot = Split-Path -Parent $PSScriptRoot
$dashboardRoot = Join-Path $vesselRoot 'dashboard'
$localState = Join-Path $dashboardRoot '.wrangler\state'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22.13 or later, then reopen PowerShell.'
}
$nodeVersion = [version](& node -p 'process.versions.node')
if ($nodeVersion -lt [version]'22.13.0') { throw 'Node.js 22.13 or later is required.' }

Push-Location $dashboardRoot
try {
    if ($Reinstall -or -not (Test-Path -LiteralPath 'node_modules')) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Dashboard dependency installation failed.' }
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed.' }

    & node scripts/setup-accounts.mjs --migrate-only
    if ($LASTEXITCODE -ne 0) { throw 'Local dashboard account migration failed.' }
    Write-Host 'First owner: cd dashboard; node scripts/setup-accounts.mjs --email YOUR_EMAIL'
    Write-Host 'Dashboard ready. In a separate terminal: cd dashboard; npm.cmd run dev'
} finally {
    Pop-Location
}
