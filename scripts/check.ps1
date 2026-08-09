$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$aiRoot = Join-Path $projectRoot "AI"
$aiPython = Join-Path $aiRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $aiPython)) {
    throw "Real AI virtual environment is missing: $aiPython"
}

$javaHomeForJobiss = $env:JOBISS_JAVA_HOME
$knownJava17 = "C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
if ([string]::IsNullOrWhiteSpace($javaHomeForJobiss) -and (Test-Path -LiteralPath $knownJava17)) {
    $javaHomeForJobiss = $knownJava17
}
if ([string]::IsNullOrWhiteSpace($javaHomeForJobiss)) {
    $javaCommand = Get-Command java -ErrorAction Stop
    $javaHomeForJobiss = Split-Path -Parent (Split-Path -Parent $javaCommand.Source)
}
$env:JAVA_HOME = $javaHomeForJobiss
$javaExecutable = Join-Path $javaHomeForJobiss "bin\java.exe"
$javaVersionOutput = (& $javaExecutable --version | Select-Object -First 1).ToString()
if ($javaVersionOutput -notmatch '\b(1[7-9]|[2-9][0-9])(?:\.|\b)') {
    throw "Java 17 or later is required. Found: $javaVersionOutput"
}

Push-Location $backendRoot
try {
    & .\gradlew.bat test
    if ($LASTEXITCODE -ne 0) {
        throw "Backend tests failed."
    }
}
finally {
    Pop-Location
}

Push-Location $aiRoot
try {
    & $aiPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "AI server tests failed."
    }
}
finally {
    Pop-Location
}

& $aiPython (Join-Path $PSScriptRoot "validate-fixtures.py")
if ($LASTEXITCODE -ne 0) {
    throw "JOBIS regression fixture validation failed."
}

Push-Location $frontendRoot
try {
    & npm.cmd run test -- --run
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend tests failed."
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed."
    }
    & npm.cmd run test:e2e
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend browser E2E tests failed."
    }
}
finally {
    Pop-Location
}

& (Join-Path $PSScriptRoot "test-local-postgres.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Isolated local PostgreSQL tests failed."
}

Write-Host "Backend, unified JOBIS AI (including Capability Graph), frontend tests/build/E2E, and isolated PostgreSQL checks passed."
