# PowerShell wrapper for ChronoGuard Live End-to-End Proof
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$ScriptDir\.."
uv run --project verifier python scripts\e2e_live.py @args
