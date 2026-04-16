param(
    [switch]$CheckOnly,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$script:RootDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $script:RootDir

$script:StepIndex = 0
$script:TotalSteps = if ($CheckOnly) { 6 } else { 10 }
$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:Summary = [ordered]@{}
$script:WingetAvailable = $false

function Write-Step {
    param([string]$Message)

    $script:StepIndex += 1
    Write-Host ("[{0}/{1}] {2}" -f $script:StepIndex, $script:TotalSteps, $Message) -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)

    Write-Host ("[信息] {0}" -f $Message)
}

function Write-Warn {
    param([string]$Message)

    $script:Warnings.Add($Message)
    Write-Host ("[警告] {0}" -f $Message) -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)

    Write-Host ("[错误] {0}" -f $Message) -ForegroundColor Red
}

function Save-Summary {
    param(
        [string]$Key,
        [string]$Value
    )

    $script:Summary[$Key] = $Value
}

function Get-CommandPath {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
        return $null
    }

    if ($command.Path) {
        return $command.Path
    }

    return $command.Source
}

function Normalize-Version {
    param([string]$VersionText)

    if ([string]::IsNullOrWhiteSpace($VersionText)) {
        return $null
    }

    return ($VersionText -replace "[^0-9.]", "")
}

function Test-MinimumVersion {
    param(
        [string]$CurrentVersion,
        [string]$MinimumVersion
    )

    try {
        return ([Version](Normalize-Version $CurrentVersion)) -ge ([Version]$MinimumVersion)
    } catch {
        return $false
    }
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (($machinePath, $userPath) | Where-Object { $_ }) -join ";"
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage,
        [string]$WorkingDirectory
    )

    $originalLocation = Get-Location
    try {
        if ($WorkingDirectory) {
            Set-Location $WorkingDirectory
        }

        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        if ($WorkingDirectory) {
            Set-Location $originalLocation
        }
    }

    if ($exitCode -ne 0) {
        throw "{0} (退出码 {1})" -f $FailureMessage, $exitCode
    }
}

function Get-PythonInfo {
    $pythonPath = Get-CommandPath -Name "python"
    if ($pythonPath) {
        $output = & $pythonPath --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $output -match "Python ([0-9]+\.[0-9]+\.[0-9]+)") {
            return [pscustomobject]@{
                Name         = "Python"
                Version      = $Matches[1]
                Path         = $pythonPath
                Command      = $pythonPath
                PrefixArgs   = @()
                Minimum      = "3.10.0"
                IsSufficient = (Test-MinimumVersion -CurrentVersion $Matches[1] -MinimumVersion "3.10.0")
            }
        }
    }

    $pyPath = Get-CommandPath -Name "py"
    if ($pyPath) {
        $output = & $pyPath -3 --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $output -match "Python ([0-9]+\.[0-9]+\.[0-9]+)") {
            return [pscustomobject]@{
                Name         = "Python"
                Version      = $Matches[1]
                Path         = $pyPath
                Command      = $pyPath
                PrefixArgs   = @("-3")
                Minimum      = "3.10.0"
                IsSufficient = (Test-MinimumVersion -CurrentVersion $Matches[1] -MinimumVersion "3.10.0")
            }
        }
    }

    return $null
}

function Get-NodeInfo {
    $nodePath = Get-CommandPath -Name "node"
    if (-not $nodePath) {
        return $null
    }

    $output = & $nodePath --version 2>&1
    if ($LASTEXITCODE -ne 0 -or $output -notmatch "v?([0-9]+\.[0-9]+\.[0-9]+)") {
        return $null
    }

    return [pscustomobject]@{
        Name         = "Node.js"
        Version      = $Matches[1]
        Path         = $nodePath
        Command      = $nodePath
        PrefixArgs   = @()
        Minimum      = "18.0.0"
        IsSufficient = (Test-MinimumVersion -CurrentVersion $Matches[1] -MinimumVersion "18.0.0")
    }
}

function Get-GitInfo {
    $gitPath = Get-CommandPath -Name "git"
    if (-not $gitPath) {
        return $null
    }

    $output = & $gitPath --version 2>&1
    if ($LASTEXITCODE -ne 0 -or $output -notmatch "git version ([0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)") {
        return $null
    }

    return [pscustomobject]@{
        Name         = "Git"
        Version      = $Matches[1]
        Path         = $gitPath
        Command      = $gitPath
        PrefixArgs   = @()
        Minimum      = "2.0.0"
        IsSufficient = (Test-MinimumVersion -CurrentVersion $Matches[1] -MinimumVersion "2.0.0")
    }
}

function Get-CliCommandInfo {
    param(
        [string]$Name,
        [string[]]$VersionArgs
    )

    if ($env:CLI_BRIDGE_INSTALLER_TEST_FORCE_NO_CLI -eq "1") {
        return $null
    }

    $path = Get-CommandPath -Name $Name
    if (-not $path) {
        return $null
    }

    $versionText = ""
    try {
        $versionText = (& $path @VersionArgs 2>&1 | Select-Object -First 1)
    } catch {
        $versionText = ""
    }

    return [pscustomobject]@{
        Name    = $Name
        Path    = $path
        Version = $versionText
    }
}

function Get-LocalCliInfo {
    return [pscustomobject]@{
        Codex  = Get-CliCommandInfo -Name "codex" -VersionArgs @("--version")
        Claude = Get-CliCommandInfo -Name "claude" -VersionArgs @("--version")
    }
}

function Get-NpmCommand {
    $npmCmd = Get-CommandPath -Name "npm.cmd"
    if ($npmCmd) {
        return $npmCmd
    }

    return Get-CommandPath -Name "npm"
}

function Install-WithWinget {
    param(
        [string]$DisplayName,
        [string]$PackageId
    )

    if (-not $script:WingetAvailable) {
        return $false
    }

    Write-Info ("使用 winget 安装 {0}" -f $DisplayName)

    & winget install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements --silent --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        Write-Warn ("winget 安装 {0} 失败，将改用官方下载。" -f $DisplayName)
        return $false
    }

    return $true
}

function Get-DownloadDirectory {
    $dir = Join-Path $env:TEMP "cli-bridge-installer"
    if (-not (Test-Path -LiteralPath $dir)) {
        [void](New-Item -ItemType Directory -Path $dir -Force)
    }

    return $dir
}

function Download-File {
    param(
        [string]$Url,
        [string]$FileName
    )

    $target = Join-Path (Get-DownloadDirectory) $FileName
    Write-Info ("下载 {0}" -f $Url)
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $target
    return $target
}

function Get-PythonInstallerUrl {
    $page = Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/downloads/windows/"
    $match = [regex]::Match($page.Content, "https://www\.python\.org/ftp/python/([0-9]+\.[0-9]+\.[0-9]+)/python-\1-amd64\.exe")
    if (-not $match.Success) {
        throw "无法解析 Python 官方安装包地址。"
    }

    return $match.Value
}

function Get-NodeInstallerUrl {
    $checksums = Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/latest-v20.x/SHASUMS256.txt"
    $match = [regex]::Match($checksums.Content, "(?m)^[0-9a-f]+\s+(node-v[0-9]+\.[0-9]+\.[0-9]+-x64\.msi)$")
    if (-not $match.Success) {
        throw "无法解析 Node.js 官方安装包地址。"
    }

    return "https://nodejs.org/dist/latest-v20.x/{0}" -f $match.Groups[1].Value
}

function Install-PythonFallback {
    $url = Get-PythonInstallerUrl
    $fileName = Split-Path -Leaf $url
    $installer = Download-File -Url $url -FileName $fileName

    Invoke-CheckedCommand -FilePath $installer -Arguments @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_test=0",
        "Include_launcher=1",
        "SimpleInstall=1"
    ) -FailureMessage "Python 安装失败"
}

function Install-NodeFallback {
    $url = Get-NodeInstallerUrl
    $fileName = Split-Path -Leaf $url
    $installer = Download-File -Url $url -FileName $fileName

    Invoke-CheckedCommand -FilePath "msiexec.exe" -Arguments @(
        "/i",
        $installer,
        "/qn",
        "/norestart"
    ) -FailureMessage "Node.js 安装失败"
}

function Install-GitFallback {
    $url = "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe"
    $installer = Download-File -Url $url -FileName "Git-64-bit.exe"

    Invoke-CheckedCommand -FilePath $installer -Arguments @(
        "/VERYSILENT",
        "/NORESTART",
        "/NOCANCEL",
        "/SP-"
    ) -FailureMessage "Git 安装失败"
}

function Ensure-Tool {
    param(
        [string]$DisplayName,
        [scriptblock]$Detector,
        [string]$MinimumVersion,
        [string]$WingetPackageId,
        [scriptblock]$FallbackInstaller
    )

    $status = & $Detector
    if ($status -and $status.IsSufficient) {
        Write-Info ("已检测到 {0} {1}" -f $DisplayName, $status.Version)
        Save-Summary -Key $DisplayName -Value $status.Version
        return $status
    }

    if ($status) {
        Write-Warn ("{0} 版本过低: {1}，需要 {2}+" -f $DisplayName, $status.Version, $MinimumVersion)
    } else {
        Write-Info ("未检测到 {0}" -f $DisplayName)
    }

    if ($CheckOnly) {
        Save-Summary -Key $DisplayName -Value "缺失或版本过低"
        return $status
    }

    $installedByWinget = Install-WithWinget -DisplayName $DisplayName -PackageId $WingetPackageId
    if ($installedByWinget) {
        Refresh-ProcessPath
        $status = & $Detector
    }

    if (-not ($status -and $status.IsSufficient)) {
        Write-Info ("切换到官方下载安装 {0}" -f $DisplayName)
        & $FallbackInstaller
        Refresh-ProcessPath
        $status = & $Detector
    }

    if (-not ($status -and $status.IsSufficient)) {
        throw "{0} 安装完成后仍不可用，请手动检查 PATH 或重新运行安装器。" -f $DisplayName
    }

    Write-Info ("{0} 已就绪: {1}" -f $DisplayName, $status.Version)
    Save-Summary -Key $DisplayName -Value $status.Version
    return $status
}

function Read-Choice {
    param(
        [string]$Prompt,
        [string[]]$Choices,
        [string]$DefaultChoice
    )

    if ($NonInteractive) {
        return $DefaultChoice
    }

    while ($true) {
        $answer = Read-Host ("{0} [默认 {1}]" -f $Prompt, $DefaultChoice)
        if ([string]::IsNullOrWhiteSpace($answer)) {
            return $DefaultChoice
        }

        if ($Choices -contains $answer) {
            return $answer
        }

        Write-Host ("请输入: {0}" -f ($Choices -join "/")) -ForegroundColor Yellow
    }
}

function Read-TextWithDefault {
    param(
        [string]$Prompt,
        [string]$DefaultValue
    )

    if ($NonInteractive) {
        return $DefaultValue
    }

    $answer = Read-Host ("{0} [默认 {1}]" -f $Prompt, $DefaultValue)
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $DefaultValue
    }

    return $answer.Trim()
}

function New-WebToken {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }

    return ([Convert]::ToBase64String($bytes)).TrimEnd("=") -replace "[+/]", "A"
}

function Select-DefaultCli {
    param([object]$CliInfo)

    if ($CliInfo.Codex -and -not $CliInfo.Claude) {
        return [pscustomobject]@{
            Type = "codex"
            Path = $CliInfo.Codex.Path
        }
    }

    if ($CliInfo.Claude -and -not $CliInfo.Codex) {
        return [pscustomobject]@{
            Type = "claude"
            Path = $CliInfo.Claude.Path
        }
    }

    if ($CliInfo.Codex -and $CliInfo.Claude) {
        $choice = Read-Choice -Prompt "选择默认 CLI：1) codex  2) claude" -Choices @("1", "2") -DefaultChoice "1"
        if ($choice -eq "2") {
            return [pscustomobject]@{
                Type = "claude"
                Path = $CliInfo.Claude.Path
            }
        }

        return [pscustomobject]@{
            Type = "codex"
            Path = $CliInfo.Codex.Path
        }
    }

    return [pscustomobject]@{
        Type = "codex"
        Path = "codex"
    }
}

function Update-EnvFromTemplate {
    param(
        [string]$TemplatePath,
        [string]$DestinationPath,
        [hashtable]$Replacements
    )

    $lines = Get-Content -Path $TemplatePath
    $updatedLines = foreach ($line in $lines) {
        if ($line -match "^(?<key>[A-Z0-9_]+)=") {
            $key = $Matches["key"]
            if ($Replacements.ContainsKey($key)) {
                "{0}={1}" -f $key, $Replacements[$key]
                continue
            }
        }

        $line
    }

    Set-Content -Path $DestinationPath -Value $updatedLines -Encoding UTF8
}

function Configure-EnvFile {
    param([object]$CliInfo)

    $envPath = Join-Path $script:RootDir ".env"
    $templatePath = Join-Path $script:RootDir ".env.example"

    if (-not (Test-Path -LiteralPath $templatePath)) {
        throw "未找到 .env.example，无法生成 .env。"
    }

    if (Test-Path -LiteralPath $envPath) {
        $overwriteChoice = Read-Choice -Prompt "检测到已有 .env：1) 保留  2) 重新生成" -Choices @("1", "2") -DefaultChoice "1"
        if ($overwriteChoice -eq "1") {
            Write-Info "保留现有 .env。"
            Save-Summary -Key ".env" -Value "保留现有配置"
            return
        }
    }

    $selectedCli = Select-DefaultCli -CliInfo $CliInfo
    $workingDir = Read-TextWithDefault -Prompt "默认工作目录" -DefaultValue $script:RootDir
    $token = New-WebToken
    $token = Read-TextWithDefault -Prompt "WEB_API_TOKEN（回车使用自动生成值）" -DefaultValue $token

    Update-EnvFromTemplate -TemplatePath $templatePath -DestinationPath $envPath -Replacements @{
        "CLI_TYPE"      = $selectedCli.Type
        "CLI_PATH"      = $selectedCli.Path
        "WORKING_DIR"   = $workingDir
        "WEB_ENABLED"   = "true"
        "WEB_HOST"      = "0.0.0.0"
        "WEB_PORT"      = "8765"
        "WEB_API_TOKEN" = $token
    }

    Write-Info (".env 已写入，默认 CLI: {0}" -f $selectedCli.Type)
    Write-Info ("WEB_API_TOKEN: {0}" -f $token)
    Save-Summary -Key ".env" -Value ("已生成（CLI={0}）" -f $selectedCli.Type)
}

function Show-CliWarning {
    Write-Warn "未检测到 codex / claude。"
    Write-Host "请先安装 Codex CLI 或 Claude Code CLI，并完成登录。"
    Write-Host "安装完成后，在 PowerShell / cmd 中确认可以运行 codex --version 或 claude --version。"
    Write-Host "然后重新运行安装器，或手动修改 .env 中的 CLI_TYPE / CLI_PATH。"
}

function Show-SummaryReport {
    Write-Host ""
    Write-Host "安装摘要" -ForegroundColor Green
    foreach ($item in $script:Summary.GetEnumerator()) {
        Write-Host ("- {0}: {1}" -f $item.Key, $item.Value)
    }

    if ($script:Warnings.Count -gt 0) {
        Write-Host ""
        Write-Host "注意事项" -ForegroundColor Yellow
        $script:Warnings | Select-Object -Unique | ForEach-Object {
            Write-Host ("- {0}" -f $_)
        }
    }
}

if ($env:CLI_BRIDGE_INSTALLER_TEST_SKIP_MAIN -eq "1") {
    return
}

try {
    Write-Step "检查仓库文件"
    foreach ($requiredPath in @("requirements.txt", "front\\package.json", ".env.example")) {
        $fullPath = Join-Path $script:RootDir $requiredPath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            throw ("缺少必要文件: {0}" -f $requiredPath)
        }
    }
    Save-Summary -Key "仓库目录" -Value $script:RootDir

    Write-Step "检查 winget"
    $script:WingetAvailable = [bool](Get-CommandPath -Name "winget")
    if ($script:WingetAvailable) {
        Write-Info "已检测到 winget。"
        Save-Summary -Key "winget" -Value "可用"
    } else {
        Write-Warn "未检测到 winget，将使用官方下载回退。"
        Save-Summary -Key "winget" -Value "不可用"
    }

    Write-Step "检查 Python 3.10+"
    $pythonInfo = Ensure-Tool -DisplayName "Python" -Detector ${function:Get-PythonInfo} -MinimumVersion "3.10.0" -WingetPackageId "Python.Python.3.12" -FallbackInstaller ${function:Install-PythonFallback}
    if ($pythonInfo -and $pythonInfo.Command -match "\\py(?:\.exe)?$" -and -not (Get-CommandPath -Name "python")) {
        Write-Warn "当前只检测到 py 启动器，start.ps1 默认使用 python 命令。若后续启动失败，请重新运行安装器或确认 Python 已加入 PATH。"
    }

    Write-Step "检查 Node.js 18+"
    $nodeInfo = Ensure-Tool -DisplayName "Node.js" -Detector ${function:Get-NodeInfo} -MinimumVersion "18.0.0" -WingetPackageId "OpenJS.NodeJS.LTS" -FallbackInstaller ${function:Install-NodeFallback}

    Write-Step "检查 Git"
    $gitInfo = Ensure-Tool -DisplayName "Git" -Detector ${function:Get-GitInfo} -MinimumVersion "2.0.0" -WingetPackageId "Git.Git" -FallbackInstaller ${function:Install-GitFallback}

    Write-Step "检查 codex / claude"
    $cliInfo = Get-LocalCliInfo
    if ($cliInfo.Codex) {
        Write-Info ("已检测到 codex: {0}" -f $cliInfo.Codex.Path)
    }
    if ($cliInfo.Claude) {
        Write-Info ("已检测到 claude: {0}" -f $cliInfo.Claude.Path)
    }

    if ($cliInfo.Codex -or $cliInfo.Claude) {
        $detectedCli = @()
        if ($cliInfo.Codex) { $detectedCli += "codex" }
        if ($cliInfo.Claude) { $detectedCli += "claude" }
        Save-Summary -Key "本地 CLI" -Value ($detectedCli -join ", ")
    } else {
        Save-Summary -Key "本地 CLI" -Value "未检测到"
        Show-CliWarning
    }

    if ($CheckOnly) {
        Show-SummaryReport
        exit 0
    }

    Write-Step "安装后端依赖"
    $pythonCommand = $pythonInfo.Command
    $pythonPrefixArgs = @($pythonInfo.PrefixArgs)
    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @($pythonPrefixArgs + @("-m", "pip", "install", "--upgrade", "pip")) -FailureMessage "升级 pip 失败" -WorkingDirectory $script:RootDir
    Invoke-CheckedCommand -FilePath $pythonCommand -Arguments @($pythonPrefixArgs + @("-m", "pip", "install", "-r", "requirements.txt")) -FailureMessage "安装后端依赖失败" -WorkingDirectory $script:RootDir
    Save-Summary -Key "后端依赖" -Value "已安装"

    Write-Step "安装前端依赖"
    $npmCommand = Get-NpmCommand
    if (-not $npmCommand) {
        throw "未找到 npm，请确认 Node.js 安装成功。"
    }
    Invoke-CheckedCommand -FilePath $npmCommand -Arguments @("install") -FailureMessage "安装前端依赖失败" -WorkingDirectory (Join-Path $script:RootDir "front")
    Save-Summary -Key "前端依赖" -Value "已安装"

    Write-Step "构建前端"
    Invoke-CheckedCommand -FilePath $npmCommand -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory (Join-Path $script:RootDir "front")
    Save-Summary -Key "前端构建" -Value "已完成"

    Write-Step "配置 .env"
    Configure-EnvFile -CliInfo $cliInfo

    Show-SummaryReport
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    Show-SummaryReport
    exit 1
}
