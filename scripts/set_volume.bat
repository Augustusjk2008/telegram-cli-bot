@echo off
:: 设置音量
:: Usage: set_volume.bat [0-100]
:: Sets master volume to specified percentage
chcp 65001 >nul

set "volume=%~1"

if "%volume%"=="" (
    :: 无参数时显示当前音量
    powershell -NoProfile -Command "Add-Type -TypeDefinition '@using System;@using System.Runtime.InteropServices;public class Volume {@DllImport(\"user32.dll\") public static extern int SendMessage(IntPtr hWnd, uint Msg, UIntPtr wParam, IntPtr lParam);@DllImport(\"user32.dll\") public static extern IntPtr GetForegroundWindow();}' 2>$null; try { [void][Volume]; $w=[Volume]::GetForegroundWindow(); [void][Volume]::SendMessage($w, 0x319, [UIntPtr]::Zero, [IntPtr](0xE*0x10000+0x40000)); Write-Host '🔊 当前音量显示在系统托盘' } catch { Write-Host '当前音量: 请查看系统托盘音量图标' }"
    exit /b 0
)

echo Setting volume to %volume%%...
powershell -NoProfile -Command "$vol = [math]::Max(0, [math]::Min(100, %volume%)); $wshell = New-Object -ComObject WScript.Shell; 1..50 | ForEach-Object { $wshell.SendKeys([char]174) }; $steps = [math]::Floor($vol / 2); if ($steps -gt 0) { 1..$steps | ForEach-Object { $wshell.SendKeys([char]175) } }; Write-Host ('Volume set to ' + $vol + '%%')"
