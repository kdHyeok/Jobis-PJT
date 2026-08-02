param(
    [int]$Port = 55432,
    [string]$MigratorPassword = "jobiss_migrator_dev",
    [string]$AppPassword = "jobiss_app_dev"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $projectRoot ".local"
$dataRoot = Join-Path $localRoot "postgres-data"
$logPath = Join-Path $localRoot "postgres.log"

$postgresInstallRoot = Join-Path $env:ProgramFiles "PostgreSQL"
$postgresVersion = Get-ChildItem -LiteralPath $postgresInstallRoot -Directory |
    Sort-Object { [int]($_.Name -split '\.')[0] } -Descending |
    Select-Object -First 1

if (-not $postgresVersion) {
    throw "PostgreSQL installation was not found under $postgresInstallRoot."
}

$postgresBin = Join-Path $postgresVersion.FullName "bin"
$initdb = Join-Path $postgresBin "initdb.exe"
$pgCtl = Join-Path $postgresBin "pg_ctl.exe"
$psql = Join-Path $postgresBin "psql.exe"
$createdb = Join-Path $postgresBin "createdb.exe"

New-Item -ItemType Directory -Force -Path $localRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $dataRoot "PG_VERSION"))) {
    $passwordFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText(
            $passwordFile,
            $MigratorPassword + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )

        & $initdb `
            --pgdata=$dataRoot `
            --username=jobiss_migrator `
            --pwfile=$passwordFile `
            --auth-host=scram-sha-256 `
            --auth-local=scram-sha-256 `
            --encoding=UTF8 `
            --locale=C

        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL initialization failed."
        }
    }
    finally {
        Remove-Item -Force -LiteralPath $passwordFile -ErrorAction SilentlyContinue
    }
}

& $pgCtl status -D $dataRoot *> $null
$isRunning = $LASTEXITCODE -eq 0

if (-not $isRunning) {
    $occupied = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($occupied) {
        throw "Port $Port is already occupied by process $($occupied[0].OwningProcess)."
    }

    & $pgCtl -D $dataRoot -l $logPath -o "-p $Port" -w start
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL startup failed. Check $logPath."
    }
}

$env:PGPASSWORD = $MigratorPassword
try {
    $databaseExists = & $psql -w -h localhost -p $Port -U jobiss_migrator -d postgres -tAc `
        "select 1 from pg_database where datname = 'jobiss'"

    if ($LASTEXITCODE -ne 0) {
        throw "Could not connect to the JOBISS local PostgreSQL cluster."
    }

    if (-not $databaseExists) {
        & $createdb -w -h localhost -p $Port -U jobiss_migrator -O jobiss_migrator jobiss
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the jobiss database."
        }
    }

    $escapedAppPassword = $AppPassword.Replace("'", "''")
    $roleSql = @"
DO `$do`$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobiss_app') THEN
        CREATE ROLE jobiss_app
            LOGIN
            PASSWORD '$escapedAppPassword'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOBYPASSRLS;
    ELSE
        ALTER ROLE jobiss_app PASSWORD '$escapedAppPassword';
    END IF;
END
`$do`$;

GRANT CONNECT ON DATABASE jobiss TO jobiss_app;
"@

    $roleSql | & $psql -w -h localhost -p $Port -U jobiss_migrator -d jobiss -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure the jobiss_app role."
    }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "JOBISS PostgreSQL is ready at localhost:$Port."
