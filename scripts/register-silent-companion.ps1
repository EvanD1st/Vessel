# Register one enrolled state's silent companion and the current user's vessel:// handler.
# Run with -StatePath <private VESSEL state directory>; -PythonPath is optional.

param(
    [Parameter(Mandatory = $true)][string]$StatePath,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$state = (Resolve-Path -LiteralPath $StatePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $state 'vessel.sqlite3') -PathType Leaf)) {
    throw "StatePath must point to an enrolled VESSEL state directory."
}

if ($PythonPath) {
    $pythonw = (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    $pythonw = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
        $found = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if (-not $found) { throw "Pass -PythonPath with the pythonw.exe that has VESSEL installed." }
        $pythonw = $found.Source
    }
}
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf) -or
    -not $pythonw.EndsWith('pythonw.exe', [StringComparison]::OrdinalIgnoreCase)) {
    throw "PythonPath must be an existing pythonw.exe."
}
& $pythonw -B -c 'import vessel'
if ($LASTEXITCODE -ne 0) { throw "The selected pythonw.exe cannot import VESSEL." }
$hasher = [Security.Cryptography.SHA256]::Create()
try {
    $stateId = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($state))).Replace('-', '').Substring(0, 12).ToLowerInvariant()
} finally {
    $hasher.Dispose()
}

# 1. Register vessel:// custom URI protocol
Write-Host "Registering vessel:// custom protocol handler..." -ForegroundColor Cyan
$regKey = "HKCU:\Software\Classes\vessel"
New-Item -Path $regKey -Force | Out-Null
Set-ItemProperty -Path $regKey -Name "(Default)" -Value "URL:VESSEL Protocol"
Set-ItemProperty -Path $regKey -Name "URL Protocol" -Value ""

$cmdKey = "$regKey\shell\open\command"
New-Item -Path $cmdKey -Force | Out-Null
$commandStr = "`"$pythonw`" -m vessel.desktop --state `"$state`" `"%1`""
Set-ItemProperty -Path $cmdKey -Name "(Default)" -Value $commandStr
Write-Host "  Protocol registered: $commandStr" -ForegroundColor Green

# 2. Add silent startup runner to Windows Startup folder
Write-Host "Setting up silent background startup daemon..." -ForegroundColor Cyan
$startupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$shortcutPath = Join-Path $startupFolder "VESSEL Companion $stateId.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m vessel.desktop --state `"$state`""
$shortcut.WindowStyle = 7 # Minimized / Hidden
$shortcut.Description = "VESSEL Agent Continuity Silent Companion"
$shortcut.Save()
$legacyShortcut = Join-Path $startupFolder 'VESSEL Companion.lnk'
if (Test-Path -LiteralPath $legacyShortcut -PathType Leaf) {
    $legacy = $wsh.CreateShortcut($legacyShortcut)
    if ($legacy.TargetPath.EndsWith('pythonw.exe', [StringComparison]::OrdinalIgnoreCase) -and
        $legacy.Arguments.StartsWith('-m vessel.desktop --state ', [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $legacyShortcut
    }
}
Write-Host "  Silent startup shortcut created at: $shortcutPath" -ForegroundColor Green

Write-Host "`nVESSEL Silent Daemon configuration complete! Companion will run quietly in the background with zero terminal windows." -ForegroundColor Green
