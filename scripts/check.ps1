$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$aiRoot = Join-Path $projectRoot "AI"
$aiPytestTemp = Join-Path $projectRoot ".local\pytest-ai-check"
$uvCommand = Get-Command uv -ErrorAction Stop

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
    $env:PYTHONUTF8 = "1"
    New-Item -ItemType Directory -Force -Path $aiPytestTemp | Out-Null
    & $uvCommand.Source run --frozen --extra dev --extra prototype pytest -q `
        --basetemp $aiPytestTemp
    if ($LASTEXITCODE -ne 0) {
        throw "AI v2bridge tests failed."
    }

    & $uvCommand.Source run --frozen --extra prototype python -m jobis_ai.explain `
        | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "AI architecture explanation check failed."
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

Write-Host "Backend, AI v2bridge, and frontend checks passed."
