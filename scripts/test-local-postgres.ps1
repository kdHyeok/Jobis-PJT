param(
    [int]$Port = 59432
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$testDataRoot = Join-Path $projectRoot ".local\postgres-test-data"
$testLogPath = Join-Path $projectRoot ".local\postgres-test.log"
$testDatabase = "jobiss_v3_integration_test"
$migratorPassword = "jobiss_migrator_test"
$appPassword = "jobiss_app_test"

& (Join-Path $PSScriptRoot "start-local-postgres.ps1") `
    -Port $Port `
    -Database $testDatabase `
    -MigratorPassword $migratorPassword `
    -AppPassword $appPassword `
    -DataDirectory $testDataRoot `
    -LogFile $testLogPath

$postgresInstallRoot = Join-Path $env:ProgramFiles "PostgreSQL"
$postgresVersion = Get-ChildItem -LiteralPath $postgresInstallRoot -Directory |
    Sort-Object { [int]($_.Name -split '\.')[0] } -Descending |
    Select-Object -First 1
$postgresBin = Join-Path $postgresVersion.FullName "bin"
$dropdb = Join-Path $postgresBin "dropdb.exe"
$createdb = Join-Path $postgresBin "createdb.exe"
$pgCtl = Join-Path $postgresBin "pg_ctl.exe"

$env:PGPASSWORD = $migratorPassword
try {
    & $dropdb -w -h localhost -p $Port -U jobiss_migrator --if-exists $testDatabase
    if ($LASTEXITCODE -ne 0) { throw "Could not reset the isolated integration database." }
    & $createdb -w -h localhost -p $Port -U jobiss_migrator -O jobiss_migrator $testDatabase
    if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated integration database." }

    $env:JOBISS_LOCAL_TEST_DB_URL = "jdbc:postgresql://localhost:$Port/$testDatabase"
    $env:JOBISS_LOCAL_TEST_DB_MIGRATOR_PASSWORD = $migratorPassword
    $env:JOBISS_LOCAL_TEST_DB_APP_PASSWORD = $appPassword
    $env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
    & (Join-Path $projectRoot "backend\gradlew.bat") `
        -p (Join-Path $projectRoot "backend") `
        test --tests com.jobiss.db.LocalPostgresIntegrationTest --rerun-tasks
    if ($LASTEXITCODE -ne 0) { throw "Local PostgreSQL integration tests failed." }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:JOBISS_LOCAL_TEST_DB_URL -ErrorAction SilentlyContinue
    Remove-Item Env:JOBISS_LOCAL_TEST_DB_MIGRATOR_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:JOBISS_LOCAL_TEST_DB_APP_PASSWORD -ErrorAction SilentlyContinue
    & $pgCtl -D $testDataRoot -m fast -w stop *> $null
}
