param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$grantPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $grantPython)) {
    throw 'Create .venv and install requirements first. See README.md.'
}
Write-Host "GrantIQ: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $grantPython -m uvicorn grantiq.app.main:app --host 127.0.0.1 --port $Port --no-proxy-headers
exit $LASTEXITCODE
