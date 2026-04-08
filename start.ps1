# Telegram CLI Bridge - Tray Startup Script
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Create tray icon
$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$iconPath = Join-Path $scriptDir "icon.ico"
if (Test-Path $iconPath) {
    $notifyIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($iconPath)
} else {
    $notifyIcon.Icon = [System.Drawing.SystemIcons]::Application
}
$notifyIcon.Text = "Telegram CLI Bridge - Running"
$notifyIcon.Visible = $true

# Create context menu
$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

# Show Console menu item
$showConsoleMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Show Console"
$showConsoleMenuItem.Add_Click({
    if ($global:pythonProcess -and !$global:pythonProcess.HasExited) {
        $sig = @'
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
[DllImport("kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
'@
        $type = Add-Type -MemberDefinition $sig -Name WinAPI -PassThru
        $hwnd = $type::GetConsoleWindow()
        if ($hwnd -ne [IntPtr]::Zero) {
            [void]$type::ShowWindow($hwnd, 9)  # SW_RESTORE
        }
    }
})
[void]$contextMenu.Items.Add($showConsoleMenuItem)

$openFolderMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Open Project Folder"
$openFolderMenuItem.Add_Click({ Start-Process explorer.exe $scriptDir })
[void]$contextMenu.Items.Add($openFolderMenuItem)

[void]$contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$statusMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Show Status"
$statusMenuItem.Add_Click({
    $statusText = if ($global:pythonProcess -and !$global:pythonProcess.HasExited) {
        "Bot is running`nPID: $($global:pythonProcess.Id)`nWorking Directory: $scriptDir"
    } else {
        "Bot process is not running`nWorking Directory: $scriptDir"
    }
    [System.Windows.Forms.MessageBox]::Show($statusText, "Telegram CLI Bridge", "OK", "Information")
})
[void]$contextMenu.Items.Add($statusMenuItem)

$restartMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Restart Service"
$restartMenuItem.Add_Click({
    if ($global:pythonProcess -and !$global:pythonProcess.HasExited) {
        $global:pythonProcess.Kill()
        $global:pythonProcess.WaitForExit(5000)
    }
    Start-Sleep -Seconds 1
    $global:pythonProcess = Start-Process python -ArgumentList "-m", "bot" -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden
    $notifyIcon.BalloonTipTitle = "Telegram CLI Bridge"
    $notifyIcon.BalloonTipText = "Service restarted"
    $notifyIcon.ShowBalloonTip(2000)
})
[void]$contextMenu.Items.Add($restartMenuItem)

[void]$contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$exitMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Exit"
$exitMenuItem.Add_Click({
    $notifyIcon.Visible = $false
    if ($global:pythonProcess -and !$global:pythonProcess.HasExited) {
        $global:pythonProcess.Kill()
        $global:pythonProcess.WaitForExit(5000)
    }
    [System.Windows.Forms.Application]::Exit()
})
[void]$contextMenu.Items.Add($exitMenuItem)

$notifyIcon.ContextMenuStrip = $contextMenu

$notifyIcon.Add_DoubleClick({
    $sig = @'
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
[DllImport("kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
'@
    $type = Add-Type -MemberDefinition $sig -Name WinAPI2 -PassThru -ErrorAction SilentlyContinue
    if (!$type) { $type = [WinAPI2] }
    $hwnd = $type::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [void]$type::ShowWindow($hwnd, 9)  # SW_RESTORE
    }
})

# Start Python Bot in new console window
$global:pythonProcess = Start-Process python -ArgumentList "-m", "bot" -WorkingDirectory $scriptDir -PassThru

$notifyIcon.BalloonTipTitle = "Telegram CLI Bridge"
$notifyIcon.BalloonTipText = "Service started"
$notifyIcon.ShowBalloonTip(2000)

# Keep script running
while (!$global:pythonProcess.HasExited) {
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.Application]::DoEvents()
}

$notifyIcon.BalloonTipTitle = "Telegram CLI Bridge"
$notifyIcon.BalloonTipText = "Service stopped!"
$notifyIcon.ShowBalloonTip(5000)

while ($true) {
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.Application]::DoEvents()
}
