$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path $projectRoot ".local\postgres-data"

if (-not (Test-Path -LiteralPath (Join-Path $dataRoot "PG_VERSION"))) {
    Write-Host "JOBIS local PostgreSQL has not been initialized."
    exit 0
}

$postgresInstallRoot = Join-Path $env:ProgramFiles "PostgreSQL"
$postgresVersion = Get-ChildItem -LiteralPath $postgresInstallRoot -Directory |
    Sort-Object { [int]($_.Name -split '\.')[0] } -Descending |
    Select-Object -First 1
$pgCtl = Join-Path $postgresVersion.FullName "bin\pg_ctl.exe"

& $pgCtl status -D $dataRoot *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "JOBIS local PostgreSQL is already stopped."
    exit 0
}

& $pgCtl -D $dataRoot -w stop -m fast
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL shutdown failed."
}

Write-Host "JOBIS local PostgreSQL stopped."
