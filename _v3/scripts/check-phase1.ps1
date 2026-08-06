$ErrorActionPreference = "Stop"

$workspace = Split-Path -Parent $PSScriptRoot
$aiRoot = Join-Path $workspace "ai-v3"
$previousSslCertDir = $env:SSL_CERT_DIR
$hadSslCertDir = Test-Path Env:SSL_CERT_DIR

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if ($hadSslCertDir) {
    Remove-Item Env:SSL_CERT_DIR
}

try {
    Invoke-Checked { python (Join-Path $PSScriptRoot "validate-fixtures.py") } "fixture validation"

    Push-Location $aiRoot
    try {
        Invoke-Checked { uv sync --dev } "dependency sync"
        Invoke-Checked { uv run python scripts\export_schemas.py } "schema export"
        Invoke-Checked { uv run pytest } "test suite"
        Invoke-Checked { uv run python scripts\smoke_server.py } "server smoke"
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($hadSslCertDir) {
        $env:SSL_CERT_DIR = $previousSslCertDir
    }
}

Write-Host "JOBIS AI v3 Phase 0-1 checks passed."
