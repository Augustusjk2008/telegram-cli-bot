# 屏幕截图
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Enable DPI awareness
Add-Type -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();' -Name WinAPI -Namespace Native
[Native.WinAPI]::SetProcessDPIAware()

# Get screen dimensions
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$bounds = $screen.Bounds

# Create bitmap and capture screen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)

# Save to temp folder
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$filename = "$env:TEMP\Screenshot_$timestamp.png"
$bitmap.Save($filename, [System.Drawing.Imaging.ImageFormat]::Png)

# Cleanup
$graphics.Dispose()
$bitmap.Dispose()

Write-Host "Screenshot saved to: $filename"
