param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Write-Host "Open http://127.0.0.1:$Port - press Ctrl+C to stop the server."
    python serve.py --port $Port
} finally { Pop-Location }
