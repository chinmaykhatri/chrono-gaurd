# PowerShell wrapper for Budget-Optimal Scheduler Simulation
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VerifierDir = Join-Path (Split-Path -Parent $ScriptDir) "chronoguard\verifier"
$SimScript = Join-Path (Split-Path -Parent $ScriptDir) "chronoguard\scripts\simulate_scheduler.py"

Push-Location $VerifierDir
try {
    uv run python $SimScript
} finally {
    Pop-Location
}
