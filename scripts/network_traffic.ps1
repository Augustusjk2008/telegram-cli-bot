# 网络流量
# 获取网络流量使用情况
# 显示所有活动网络接口的发送和接收流量

function Format-Bytes {
    param([long]$Bytes)
    
    if ($Bytes -gt 1TB) {
        return "{0:N2} TB" -f ($Bytes / 1TB)
    }
    elseif ($Bytes -gt 1GB) {
        return "{0:N2} GB" -f ($Bytes / 1GB)
    }
    elseif ($Bytes -gt 1MB) {
        return "{0:N2} MB" -f ($Bytes / 1MB)
    }
    elseif ($Bytes -gt 1KB) {
        return "{0:N2} KB" -f ($Bytes / 1KB)
    }
    else {
        return "$Bytes B"
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "       网络流量使用情况统计" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 获取所有网络接口统计信息
$networkStats = Get-NetAdapterStatistics | Where-Object { $_.ReceivedBytes -gt 0 -or $_.SentBytes -gt 0 }

if ($networkStats) {
    $totalReceived = 0
    $totalSent = 0
    
    foreach ($adapter in $networkStats) {
        $received = $adapter.ReceivedBytes
        $sent = $adapter.SentBytes
        $totalReceived += $received
        $totalSent += $sent
        
        Write-Host "接口: $($adapter.Name)" -ForegroundColor Yellow
        Write-Host "  接收流量: $(Format-Bytes -Bytes $received)" -ForegroundColor Green
        Write-Host "  发送流量: $(Format-Bytes -Bytes $sent)" -ForegroundColor Green
        Write-Host "  总流量:   $(Format-Bytes -Bytes ($received + $sent))" -ForegroundColor Green
        Write-Host ""
    }
    
    Write-Host "----------------------------------------" -ForegroundColor Gray
    Write-Host "总接收流量: $(Format-Bytes -Bytes $totalReceived)" -ForegroundColor Magenta
    Write-Host "总发送流量: $(Format-Bytes -Bytes $totalSent)" -ForegroundColor Magenta
    Write-Host "总流量:     $(Format-Bytes -Bytes ($totalReceived + $totalSent))" -ForegroundColor Magenta
} else {
    Write-Host "未找到活动的网络接口或没有流量数据。" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
