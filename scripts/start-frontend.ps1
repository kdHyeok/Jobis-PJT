param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$nodeModules = Join-Path $frontendRoot "node_modules"
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue

if (-not $npm) {
    throw "npm was not found. Install Node.js and open a new terminal."
}

Push-Location $frontendRoot
try {
    if ($Install -or -not (Test-Path -LiteralPath $nodeModules)) {
        & $npm.Source install
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependencies failed to install."
        }
    }

    & $npm.Source run dev
    if ($LASTEXITCODE -ne 0) {
        throw "JOBIS frontend stopped with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
