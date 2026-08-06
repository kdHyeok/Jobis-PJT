param(
    [int]$Port = 8400
)

$ErrorActionPreference = "Stop"
$listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "No AI server is listening on port $Port."
    exit 0
}

$processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
    if (-not $process -or $process.CommandLine -notmatch "jobis_ai\.v2bridge\.app:app") {
        throw "Refusing to stop PID $processId because port $Port is not owned by the JOBIS AI bridge."
    }

    Write-Host "Stopping JOBIS AI process tree (PID $processId)..."
    & taskkill.exe /PID $processId /T /F
    if ($LASTEXITCODE -ne 0) {
        throw "Could not stop the JOBIS AI process tree (PID $processId)."
    }
}
