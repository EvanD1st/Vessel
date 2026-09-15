param(
    [string]$Workspace,
    [string]$State,
    [string]$Mission,
    [string]$McpConfig,
    [string]$Origin,
    [int]$Port,
    [int]$Ttl,
    [switch]$EnableStartup,
    [switch]$Launch,
    [switch]$NonInteractive
)
$ErrorActionPreference = 'Stop'
$vesselRoot = Split-Path -Parent $PSScriptRoot
$vesselInterpreter = Join-Path $vesselRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vesselInterpreter)) {
    throw 'Run scripts/setup.ps1 once to install VESSEL, then rerun setup-project.ps1.'
}
$vesselSetupArgs = @('-m', 'vessel')
if ($State) { $vesselSetupArgs += @('--state', $State) }
$vesselSetupArgs += 'setup'
if ($Workspace) { $vesselSetupArgs += @('--workspace', $Workspace) }
if ($Mission) { $vesselSetupArgs += @('--mission', $Mission) }
if ($McpConfig) { $vesselSetupArgs += @('--mcp-config', $McpConfig) }
if ($Origin) { $vesselSetupArgs += @('--origin', $Origin) }
if ($PSBoundParameters.ContainsKey('Port')) { $vesselSetupArgs += @('--port', $Port) }
if ($PSBoundParameters.ContainsKey('Ttl')) { $vesselSetupArgs += @('--ttl', $Ttl) }
if ($EnableStartup) { $vesselSetupArgs += '--startup' }
if ($Launch) { $vesselSetupArgs += '--launch' }
if ($NonInteractive) { $vesselSetupArgs += '--yes' }
& $vesselInterpreter @vesselSetupArgs
if ($LASTEXITCODE -ne 0) { throw 'Project setup did not complete. Read the error above; existing work is preserved.' }
