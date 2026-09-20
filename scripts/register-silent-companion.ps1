# Registers VESSEL silent companion daemon and vessel:// protocol handler for the current user.
# Zero administrator privileges required (uses HKCU).

$ErrorActionPreference = "Stop"

$pythonw = "C:\Users\USER\AppData\Local\Programs\Python\Python314\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $found = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($found) { $pythonw = $found.Source } else { $pythonw = "pythonw.exe" }
}

$statePath = "C:\Users\USER\AppData\Local\VESSEL\projects\6d192de427b15783"

# 1. Register vessel:// custom URI protocol
Write-Host "Registering vessel:// custom protocol handler..." -ForegroundColor Cyan
$regKey = "HKCU:\Software\Classes\vessel"
New-Item -Path $regKey -Force | Out-Null
Set-ItemProperty -Path $regKey -Name "(Default)" -Value "URL:VESSEL Protocol"
Set-ItemProperty -Path $regKey -Name "URL Protocol" -Value ""

$cmdKey = "$regKey\shell\open\command"
New-Item -Path $cmdKey -Force | Out-Null
$commandStr = "`"$pythonw`" -m vessel.desktop --state `"$statePath`""
Set-ItemProperty -Path $cmdKey -Name "(Default)" -Value $commandStr
Write-Host "  Protocol registered: $commandStr" -ForegroundColor Green

# 2. Add silent startup runner to Windows Startup folder
Write-Host "Setting up silent background startup daemon..." -ForegroundColor Cyan
$startupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$shortcutPath = Join-Path $startupFolder "VESSEL Companion.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m vessel.desktop --state `"$statePath`""
$shortcut.WindowStyle = 7 # Minimized / Hidden
$shortcut.Description = "VESSEL Agent Continuity Silent Companion"
$shortcut.Save()
Write-Host "  Silent startup shortcut created at: $shortcutPath" -ForegroundColor Green

Write-Host "`nVESSEL Silent Daemon configuration complete! Companion will run quietly in the background with zero terminal windows." -ForegroundColor Green
