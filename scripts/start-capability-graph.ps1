param(
    [int]$Port = 8600,
    [switch]$Install,
    [string]$SharedSecret = "local-capability-graph-secret",
    [string]$ReleasePath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$aiRoot = Join-Path $projectRoot "AI"
$python = Join-Path $aiRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3.12 -m venv (Join-Path $aiRoot ".venv")
    }
    else {
        & python -m venv (Join-Path $aiRoot ".venv")
    }
    $Install = $true
}

if ($Install) {
    Push-Location $aiRoot
    try {
        & $python -m pip install -e ".[dev,prototype]"
        if ($LASTEXITCODE -ne 0) {
            throw "JOBIS AI dependencies failed to install."
        }
    }
    finally {
        Pop-Location
    }
}

$env:JOBIS_GRAPH_SHARED_SECRET = $SharedSecret
if ([string]::IsNullOrWhiteSpace($ReleasePath)) {
    Remove-Item Env:JOBIS_GRAPH_DATASET_PATH -ErrorAction SilentlyContinue
}
else {
    $env:JOBIS_GRAPH_DATASET_PATH = $ReleasePath
}

Push-Location $aiRoot
try {
    Write-Host "Starting optional Capability Graph HTTP facade at http://127.0.0.1:$Port..." -ForegroundColor Cyan
    & $python -m uvicorn jobis_ai.capability_graph_server.app:app --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
