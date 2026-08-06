param(
    [string]$JavaHome = "C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$javaExecutable = Join-Path $JavaHome "bin\java.exe"

if (-not (Test-Path -LiteralPath $javaExecutable)) {
    throw "Java 17 was not found at $javaExecutable. Pass -JavaHome with a valid JDK path."
}

$env:JAVA_HOME = $JavaHome
$env:Path = (Join-Path $JavaHome "bin") + ";" + $env:Path

Write-Host "Preparing the isolated JOBIS PostgreSQL cluster..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "start-local-postgres.ps1")

Push-Location $backendRoot
try {
    & .\gradlew.bat bootRun
    if ($LASTEXITCODE -ne 0) {
        throw "JOBIS backend stopped with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
