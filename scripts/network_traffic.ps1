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

Write-Output "========================================"
Write-Output "       Network Traffic Usage"
Write-Output "========================================"
Write-Output ""

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
        
        Write-Output "Interface: $($adapter.Name)"
        Write-Output "  ReceivedBytes: $(Format-Bytes -Bytes $received)"
        Write-Output "  SentBytes: $(Format-Bytes -Bytes $sent)"
        Write-Output "  TotalBytes: $(Format-Bytes -Bytes ($received + $sent))"
        Write-Output ""
    }
    
    Write-Output "----------------------------------------"
    Write-Output "TotalReceived: $(Format-Bytes -Bytes $totalReceived)"
    Write-Output "TotalSent: $(Format-Bytes -Bytes $totalSent)"
    Write-Output "TotalTraffic: $(Format-Bytes -Bytes ($totalReceived + $totalSent))"
} else {
    Write-Output "No active network adapters or traffic data found."
}

Write-Output ""
Write-Output "========================================"
