$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$aiRoot = Join-Path $projectRoot "ai-server"
$aiPython = Join-Path $aiRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $aiPython)) {
    throw "AI server virtual environment is missing: $aiPython"
}

$javaCommand = Get-Command java -ErrorAction Stop
$javaHomeForJobiss = Split-Path -Parent (Split-Path -Parent $javaCommand.Source)
$env:JAVA_HOME = $javaHomeForJobiss
$javaVersionOutput = (& java --version | Select-Object -First 1).ToString()
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
    & $aiPython -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "AI server tests failed."
    }

    & $aiPython -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "AI server lint failed."
    }
}
finally {
    Pop-Location
}

Push-Location $frontendRoot
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed."
    }
}
finally {
    Pop-Location
}

Write-Host "All available JOBISS checks passed."
