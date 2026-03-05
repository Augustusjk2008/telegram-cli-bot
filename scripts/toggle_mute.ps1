# 静音切换
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class VolumeControl {
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, uint dwExtraInfo);
    
    public static void ToggleMute() {
        // VK_VOLUME_MUTE = 0xAD
        // KEYEVENTF_KEYUP = 0x0002
        keybd_event(0xAD, 0, 0, 0);
        keybd_event(0xAD, 0, 2, 0);
    }
}
'@

[VolumeControl]::ToggleMute()
Write-Host "Mute toggled"
