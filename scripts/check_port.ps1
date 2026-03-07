# Check which process is using a port
param([int]$Port = 8080)

Write-Host "Checking port $Port..." -ForegroundColor Cyan
Write-Host ""

try {
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host "Port $Port is FREE" -ForegroundColor Green
        exit 0
    }

    Write-Host "Port $Port is in use by:" -ForegroundColor Yellow
    Write-Host ""

    foreach ($conn in $connections) {
        $proc = $null
        try {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        } catch {}

        Write-Host "  PID: $($conn.OwningProcess)" -ForegroundColor Cyan -NoNewline
        
        if ($proc) {
            Write-Host " | Name: $($proc.ProcessName)" -NoNewline
            Write-Host " | Path: $($proc.Path)" -ForegroundColor Gray
        } else {
            Write-Host " | (cannot get process info)" -ForegroundColor Red
        }
        Write-Host ""
    }

} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
