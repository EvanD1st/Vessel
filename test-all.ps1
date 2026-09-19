# All-in-one verification script for VESSEL: Orbio Integration, Dashboard, and Extension
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VESSEL All-In-One Verification Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Python Test Suite (Core Orbio & Companion)
Write-Host "`n[1/4] Running Python Orbio & Companion Tests..." -ForegroundColor Yellow
& .venv\Scripts\python.exe -m pytest tests/test_orbio.py tests/test_dashboard.py tests/test_extension_api.py
if ($LASTEXITCODE -ne 0) { Write-Error "Python tests failed."; exit 1 }

# 2. Dashboard Tests & Typecheck
Write-Host "`n[2/4] Running Dashboard Tests (Pairing, Orbio, Lint, Typecheck)..." -ForegroundColor Yellow
Push-Location dashboard
try {
    npm run test:pairing
    if ($LASTEXITCODE -ne 0) { Write-Error "Dashboard pairing test failed."; exit 1 }
    
    npm run test:orbio
    if ($LASTEXITCODE -ne 0) { Write-Error "Dashboard Orbio test failed."; exit 1 }
    
    npm run lint
    if ($LASTEXITCODE -ne 0) { Write-Error "Dashboard linting failed."; exit 1 }
    
    npx tsc --noEmit
    if ($LASTEXITCODE -ne 0) { Write-Error "Dashboard TypeScript verification failed."; exit 1 }
} finally {
    Pop-Location
}

# 3. VS Code Extension Verification
Write-Host "`n[3/4] Verifying VS Code Extension Build & VSIX Package..." -ForegroundColor Yellow
Push-Location vscode-extension
try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { Write-Error "VS Code extension typecheck failed."; exit 1 }
    
    npm run lint
    if ($LASTEXITCODE -ne 0) { Write-Error "VS Code extension linting failed."; exit 1 }
    
    npm run test:package
    if ($LASTEXITCODE -ne 0) { Write-Error "VS Code extension package verification failed."; exit 1 }
} finally {
    Pop-Location
}

# 4. CLI Orbio Integration
Write-Host "`n[4/4] Verifying CLI Orbio Commands..." -ForegroundColor Yellow
& .\vessel.cmd orbio --help > $null
if ($LASTEXITCODE -ne 0) { Write-Error "CLI orbio command failed."; exit 1 }

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  ALL TESTS PASSED! System is ready.   " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
