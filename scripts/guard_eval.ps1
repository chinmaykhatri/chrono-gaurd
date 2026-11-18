$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$ScriptDir\..\chronoguard\eval\run_guard_eval.py"
exit $LASTEXITCODE
