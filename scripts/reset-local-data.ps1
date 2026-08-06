[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$port = 58432
$database = "jobiss_v3_integration_lab"
$migratorUser = "jobiss_migrator"
$migratorPassword = "jobiss_migrator_dev"
$expectedDataRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $projectRoot ".local\postgres-data")
)

$expectedProjectRoot = [System.IO.Path]::GetFullPath("C:\JOBIS")
if ([System.IO.Path]::GetFullPath($projectRoot) -ne $expectedProjectRoot) {
    throw "Refusing to reset data outside $expectedProjectRoot."
}

if (-not $Force) {
    Write-Host ""
    Write-Host "JOBIS v3 integration lab data reset" -ForegroundColor Yellow
    Write-Host "Target: localhost:$port/$database"
    Write-Host "Accounts, conversations, postings, analyses, roadmaps, and uploaded career data will be deleted."
    Write-Host "Flyway migrations and baseline catalog data will be rebuilt the next time the backend starts."
    Write-Host ""
    $confirmation = Read-Host "Type RESET to continue"
    if ($confirmation -cne "RESET") {
        Write-Host "Data reset cancelled."
        return
    }
}

$postgresInstallRoot = Join-Path $env:ProgramFiles "PostgreSQL"
$postgresVersion = Get-ChildItem -LiteralPath $postgresInstallRoot -Directory -ErrorAction Stop |
    Sort-Object { [int]($_.Name -split '\.')[0] } -Descending |
    Select-Object -First 1

if (-not $postgresVersion) {
    throw "PostgreSQL installation was not found under $postgresInstallRoot."
}

$postgresBin = Join-Path $postgresVersion.FullName "bin"
$psql = Join-Path $postgresBin "psql.exe"
$dropdb = Join-Path $postgresBin "dropdb.exe"
$createdb = Join-Path $postgresBin "createdb.exe"

foreach ($tool in @($psql, $dropdb, $createdb)) {
    if (-not (Test-Path -LiteralPath $tool)) {
        throw "Required PostgreSQL tool was not found: $tool"
    }
}

Write-Host "Stopping JOBIS services before resetting the database..."
& (Join-Path $PSScriptRoot "stop-all.ps1")

Write-Host "Starting the isolated JOBIS PostgreSQL cluster..."
& (Join-Path $PSScriptRoot "start-local-postgres.ps1") `
    -Port $port `
    -Database $database `
    -MigratorPassword $migratorPassword

if (-not (Test-Path -LiteralPath (Join-Path $expectedDataRoot "PG_VERSION"))) {
    throw "The isolated PostgreSQL data directory was not found at $expectedDataRoot."
}

$env:PGPASSWORD = $migratorPassword
try {
    $identity = & $psql -X -w -h localhost -p $port -U $migratorUser -d postgres -tAc `
        "select current_database() || '|' || inet_server_port() || '|' || current_user"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify the isolated JOBIS PostgreSQL connection."
    }

    if ($identity.Trim() -ne "postgres|$port|$migratorUser") {
        throw "Refusing to reset an unexpected PostgreSQL target: $($identity.Trim())"
    }

    $owner = & $psql -X -w -h localhost -p $port -U $migratorUser -d postgres -tAc `
        "select pg_get_userbyid(datdba) from pg_database where datname = '$database'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify the JOBIS database owner."
    }
    if ($owner -and $owner.Trim() -ne $migratorUser) {
        throw "Refusing to reset $database because its owner is $($owner.Trim())."
    }

    & $psql -X -w -h localhost -p $port -U $migratorUser -d postgres -v ON_ERROR_STOP=1 -c `
        "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$database' and pid <> pg_backend_pid();"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not close existing connections to $database."
    }

    & $dropdb -w -h localhost -p $port -U $migratorUser --if-exists $database
    if ($LASTEXITCODE -ne 0) {
        throw "Could not drop the isolated JOBIS database."
    }

    & $createdb -w -h localhost -p $port -U $migratorUser -O $migratorUser $database
    if ($LASTEXITCODE -ne 0) {
        throw "Could not recreate the isolated JOBIS database."
    }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "The isolated JOBIS database has been recreated." -ForegroundColor Green
Write-Host "No application server was started." -ForegroundColor Yellow
Write-Host "Start the backend when you are ready; Flyway will rebuild the schema and baseline data." -ForegroundColor Green
