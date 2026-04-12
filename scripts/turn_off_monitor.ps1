# 关闭显示器
$ErrorActionPreference = "Stop"

try {
    if (-not ("DisplayPower" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DisplayPower {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd,
        uint Msg,
        IntPtr wParam,
        IntPtr lParam,
        uint fuFlags,
        uint uTimeout,
        out IntPtr lpdwResult
    );

    public static void TurnOffMonitor() {
        IntPtr HWND_BROADCAST = new IntPtr(0xFFFF);
        uint WM_SYSCOMMAND = 0x0112;
        IntPtr SC_MONITORPOWER = new IntPtr(0xF170);
        IntPtr MONITOR_OFF = new IntPtr(2);
        uint SMTO_ABORTIFHUNG = 0x0002;
        IntPtr result;

        SendMessageTimeout(
            HWND_BROADCAST,
            WM_SYSCOMMAND,
            SC_MONITORPOWER,
            MONITOR_OFF,
            SMTO_ABORTIFHUNG,
            1000,
            out result
        );
    }
}
'@
    }

    Write-Output "Turning off screen..."
    [DisplayPower]::TurnOffMonitor()
    Write-Output "Done"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
