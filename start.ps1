# Telegram CLI Bridge Bot 启动脚本
# 支持 PowerShell 5.1+ 和 PowerShell Core

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Telegram CLI Bridge Bot"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   Telegram CLI Bridge Bot 启动脚本" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 检查 .env 文件
if (-not (Test-Path ".env")) {
    Write-Host "[警告] 未找到 .env 文件，请配置环境变量！" -ForegroundColor Yellow
    Read-Host "按 Enter 键继续"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "   正在启动 Bot..." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""

# 启动 Bot
try {
    python -m bot
} catch {
    Write-Host "[错误] Bot 运行出错: $_" -ForegroundColor Red
}

# 如果 Bot 异常退出
Write-Host ""
Write-Host "[错误] Bot 已停止运行！" -ForegroundColor Red
Read-Host "按 Enter 键退出"
