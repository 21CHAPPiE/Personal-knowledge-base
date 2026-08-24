# 一键启动前后端（开发模式）。Ctrl+C 同时结束两个进程。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$backend = Start-Process -NoNewWindow -PassThru `
    -FilePath python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend")
Write-Host "backend: http://127.0.0.1:8000  (PID $PID)"

$frontend = Start-Process -NoNewWindow -PassThru `
    -FilePath npm -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $root "frontend")
Write-Host "frontend: http://127.0.0.1:5173"

try {
    while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Milliseconds 500 }
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force }
}
Write-Host "both stopped"
