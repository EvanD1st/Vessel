param([string]$Python)
$ErrorActionPreference = 'Stop'
$vesselRoot = Split-Path -Parent $PSScriptRoot
$vesselInterpreter = Join-Path $vesselRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vesselInterpreter)) {
    if ($Python) {
        & $Python -m venv (Join-Path $vesselRoot '.venv')
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv (Join-Path $vesselRoot '.venv')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $vesselRoot '.venv')
    } else {
        throw 'Python 3.11+ is required. Pass -Python with the full path to python.exe.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
& $vesselInterpreter -m pip install -r (Join-Path $vesselRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $vesselInterpreter -m pip install --no-deps -e $vesselRoot
if ($LASTEXITCODE -ne 0) { throw 'VESSEL installation failed.' }
& $vesselInterpreter -m vessel --version
