param(
    [int]$Port = 8600,
    [switch]$Install,
    [string]$GraphRoot = "C:\jobiss-capability-graph-lab",
    [string]$SharedSecret = "local-capability-graph-secret"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $GraphRoot ".venv\Scripts\python.exe"
$dataset = Join-Path $GraphRoot "data\seed.v2.yaml"

if (-not (Test-Path -LiteralPath $GraphRoot)) {
    throw "Capability Graph workspace is missing: $GraphRoot"
}
if (-not (Test-Path -LiteralPath $dataset)) {
    throw "Capability Graph dataset is missing: $dataset"
}
if ($SharedSecret.Length -lt 16) {
    throw "SharedSecret must contain at least 16 characters."
}

if ($Install -or -not (Test-Path -LiteralPath $python)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        throw "uv is required to install the Capability Graph environment."
    }
    Push-Location $GraphRoot
    try {
        & $uv.Source sync --dev
        if ($LASTEXITCODE -ne 0) {
            throw "Capability Graph dependencies failed to install."
        }
    }
    finally {
        Pop-Location
    }
}

$env:JOBIS_GRAPH_ENVIRONMENT = "local"
$env:JOBIS_GRAPH_SHARED_SECRET = $SharedSecret
$env:JOBIS_GRAPH_DATASET_PATH = $dataset

Push-Location $GraphRoot
try {
    Write-Host "Starting JOBIS Capability Graph at http://127.0.0.1:$Port..." -ForegroundColor Cyan
    & $python -m uvicorn jobis_capability_graph.api:app --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Capability Graph stopped with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
