$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$ScriptDir\..\eval\run_guard_eval.py"
exit $LASTEXITCODE
