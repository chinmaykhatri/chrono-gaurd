# PowerShell wrapper for ChronoGuard verify-proof (Gate G1)
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$ScriptDir\.."
uv run --project verifier python scripts\verify_proof.py @args
exit $LASTEXITCODE
