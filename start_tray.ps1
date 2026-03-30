# Telegram CLI Bridge - Tray Startup Script
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Create tray icon
$notifyIcon = New-Object System.Windows.Forms.NotifyIcon

# Try to load custom icon, otherwise use default
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

# Open project folder menu item
$openFolderMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Open Project Folder"
$openFolderMenuItem.Add_Click({
    Start-Process explorer.exe $scriptDir
})
[void]$contextMenu.Items.Add($openFolderMenuItem)

[void]$contextMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

# Status menu item
$statusMenuItem = New-Object System.Windows.Forms.ToolStripMenuItem "Show Status"
$statusMenuItem.Add_Click({
    $statusText = if ($global:pythonProcess -and !$global:pythonProcess.HasExited) {
        "Bot is running in tray.`nPID: $($global:pythonProcess.Id)`nWorking Directory: $scriptDir"
    } else {
        "Bot process is not running.`nWorking Directory: $scriptDir"
    }
    [System.Windows.Forms.MessageBox]::Show($statusText, "Telegram CLI Bridge", "OK", "Information")
})
[void]$contextMenu.Items.Add($statusMenuItem)

# Restart menu item
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

# Exit menu item
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

# Double click to show status window
$notifyIcon.Add_DoubleClick({
    [System.Windows.Forms.MessageBox]::Show("Bot is running in tray.`nWorking Directory: $scriptDir", "Telegram CLI Bridge", "OK", "Information")
})

# Start Python Bot hidden
$global:mainHwnd = $null
$global:pythonProcess = Start-Process python -ArgumentList "-m", "bot" -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden

# Show startup notification
$notifyIcon.BalloonTipTitle = "Telegram CLI Bridge"
$notifyIcon.BalloonTipText = "Service started"
$notifyIcon.ShowBalloonTip(2000)

# Keep script running, process tray events
while (!$global:pythonProcess.HasExited) {
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.Application]::DoEvents()
}

# If Python process exits unexpectedly, show error
$notifyIcon.BalloonTipTitle = "Telegram CLI Bridge"
$notifyIcon.BalloonTipText = "Service stopped!"
$notifyIcon.ShowBalloonTip(5000)

# Wait for user to click exit
while ($true) {
    Start-Sleep -Milliseconds 100
    [System.Windows.Forms.Application]::DoEvents()
}
