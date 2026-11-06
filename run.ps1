# Start ptgateway (Windows). Uses .venv if present, else the python on PATH.
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
Set-Location $PSScriptRoot
& $py -m ptgateway @args
