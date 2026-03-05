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

# 检查虚拟环境
$VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
$VenvActivate = Join-Path $ScriptDir "venv\Scripts\Activate.ps1"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[警告] 未找到虚拟环境，正在创建..." -ForegroundColor Yellow
    try {
        python -m venv venv
        Write-Host "[成功] 虚拟环境创建完成" -ForegroundColor Green
    } catch {
        Write-Host "[错误] 创建虚拟环境失败！请确保已安装 Python 3.8+" -ForegroundColor Red
        Read-Host "按 Enter 键退出"
        exit 1
    }
}

# 激活虚拟环境
& $VenvActivate

# 检查依赖是否需要安装
$DepsFlag = Join-Path $ScriptDir "venv\.dependencies_installed"
if (-not (Test-Path $DepsFlag)) {
    Write-Host "[信息] 正在安装依赖..." -ForegroundColor Cyan
    try {
        pip install -r requirements.txt
        New-Item -ItemType File -Path $DepsFlag -Force | Out-Null
        Write-Host "[成功] 依赖安装完成" -ForegroundColor Green
    } catch {
        Write-Host "[错误] 安装依赖失败！" -ForegroundColor Red
        Read-Host "按 Enter 键退出"
        exit 1
    }
}

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
