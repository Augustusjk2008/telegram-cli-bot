param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [string]$Repository = "Augustusjk2008/telegram-cli-bot",
    [string]$TargetRef = "HEAD",
    [ValidateSet("BuildAndPublish", "BuildOnly", "PublishOnly")]
    [string]$Mode = "BuildAndPublish",
    [switch]$SkipChecks,
    [switch]$SkipBuild,
    [switch]$SkipPublish,
    [switch]$AllowDirtyWorktree
)

$ErrorActionPreference = "Stop"

$script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script:RepoRoot = Split-Path -Parent $script:ScriptDir
$script:ArtifactsDir = Join-Path $script:ScriptDir "artifacts"
$script:StageRoot = Join-Path $script:ScriptDir "stage"
$script:FrontDir = Join-Path $script:RepoRoot "front"
$script:PackageBaseName = "orbit-safe-claw"

function Write-Step {
    param([string]$Message)

    Write-Host ("[步骤] {0}" -f $Message) -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)

    Write-Host ("[信息] {0}" -f $Message)
}

function Resolve-RequestedMode {
    $resolvedMode = $Mode

    if ($SkipPublish) {
        if ($resolvedMode -eq "PublishOnly") {
            throw "-SkipPublish 与 -Mode PublishOnly 不能同时使用。"
        }
        if ($resolvedMode -eq "BuildAndPublish") {
            $resolvedMode = "BuildOnly"
        }
    }

    return $resolvedMode
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $originalLocation = Get-Location
    try {
        Set-Location $WorkingDirectory
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        Set-Location $originalLocation
    }

    if ($exitCode -ne 0) {
        throw "{0} (退出码 {1})" -f $FailureMessage, $exitCode
    }
}

function Invoke-Git {
    param(
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    $output = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $detail = ($output | Out-String).Trim()
        if ($detail) {
            throw "{0}: {1}" -f $FailureMessage, $detail
        }
        throw $FailureMessage
    }
    return @($output)
}

function Normalize-Version {
    param([string]$Value)

    $text = [string]::IsNullOrWhiteSpace($Value) ? "" : $Value.Trim()
    if ($text.StartsWith("v")) {
        return $text.Substring(1)
    }
    return $text
}

function Get-VersionFromFile {
    param(
        [string]$Path,
        [string]$Pattern,
        [string]$Label
    )

    $match = Select-String -Path $Path -Pattern $Pattern | Select-Object -First 1
    if (-not $match) {
        throw "无法从 $Label 读取版本号: $Path"
    }
    return $match.Matches[0].Groups["version"].Value
}

function Assert-CleanTrackedWorktree {
    $status = & git status --short --untracked-files=no
    if ($LASTEXITCODE -ne 0) {
        throw "无法读取 git 状态。"
    }
    if (($status | Out-String).Trim()) {
        throw "存在未提交的 tracked 改动，请先提交后再发布。"
    }
}

function Assert-VersionMatchesTag {
    $backendVersion = Get-VersionFromFile -Path (Join-Path $script:RepoRoot "bot\version.py") -Pattern 'APP_VERSION = "(?<version>[^"]+)"' -Label "后端版本"
    $frontendVersion = Get-VersionFromFile -Path (Join-Path $script:RepoRoot "front\src\theme.ts") -Pattern 'APP_VERSION = "(?<version>[^"]+)"' -Label "前端版本"
    $normalizedTag = Normalize-Version $Tag

    if ($backendVersion -ne $frontendVersion) {
        throw "前后端版本不一致: backend=$backendVersion frontend=$frontendVersion"
    }
    if ($backendVersion -ne $normalizedTag) {
        throw "版本号与 tag 不一致: version=$backendVersion tag=$Tag"
    }

    Write-Info ("版本校验通过: {0}" -f $backendVersion)
}

function Reset-Directory {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    [void](New-Item -ItemType Directory -Path $Path -Force)
}

function Invoke-ReleasePrepChecks {
    Write-Step "运行后端发布检查"
    Invoke-CheckedCommand -FilePath "python" -Arguments @(
        "-m", "pytest",
        "tests/test_install_scripts.py",
        "tests/test_start_scripts.py",
        "tests/test_updater.py",
        "tests/test_web_api.py",
        "tests/test_release_assets.py",
        "-q"
    ) -FailureMessage "后端发布检查失败"

    Write-Step "运行前端发布检查"
    Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @(
        "test",
        "--",
        "src/test/settings-screen.test.tsx",
        "src/test/real-client.test.ts"
    ) -FailureMessage "前端发布检查失败" -WorkingDirectory $script:FrontDir

    Write-Step "构建前端"
    Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory $script:FrontDir
}

function Invoke-BuildOnly {
    Write-Step "构建前端"
    Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory $script:FrontDir
}

function Ensure-TagAtTarget {
    $existingTag = & git rev-parse -q --verify ("refs/tags/{0}" -f $Tag) 2>$null
    if ($LASTEXITCODE -eq 0 -and $existingTag) {
        $tagCommit = (Invoke-Git -Arguments @("rev-list", "-n", "1", $Tag) -FailureMessage "读取 tag 提交失败" | Select-Object -First 1).Trim()
        $targetCommit = (Invoke-Git -Arguments @("rev-parse", $TargetRef) -FailureMessage "读取目标提交失败" | Select-Object -First 1).Trim()
        if ($tagCommit -ne $targetCommit) {
            throw "tag $Tag 已存在，但不指向 $TargetRef。"
        }
        Write-Info ("tag 已存在并指向目标提交: {0}" -f $Tag)
        return
    }

    Write-Step ("创建 tag {0}" -f $Tag)
    Invoke-CheckedCommand -FilePath "git" -Arguments @("tag", "-a", $Tag, $TargetRef, "-m", ("Release {0}" -f $Tag)) -FailureMessage "创建 tag 失败"
}

function Copy-TrackedFilesToStage {
    param([string]$StageDir)

    Write-Step "复制 tracked 文件到暂存区"
    $trackedFiles = Invoke-Git -Arguments @("ls-files") -FailureMessage "读取 tracked 文件失败"
    foreach ($relativePath in $trackedFiles) {
        $cleanPath = [string]$relativePath
        if ([string]::IsNullOrWhiteSpace($cleanPath)) {
            continue
        }
        $sourcePath = Join-Path $script:RepoRoot $cleanPath
        $destinationPath = Join-Path $StageDir $cleanPath
        $destinationDir = Split-Path -Parent $destinationPath
        if ($destinationDir) {
            [void](New-Item -ItemType Directory -Path $destinationDir -Force)
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }

    $frontDist = Join-Path $script:FrontDir "dist"
    if (-not (Test-Path -LiteralPath $frontDist)) {
        throw "未找到 front/dist，请先完成前端构建。"
    }

    $frontDistTarget = Join-Path $StageDir "front\dist"
    if (Test-Path -LiteralPath $frontDistTarget) {
        Remove-Item -LiteralPath $frontDistTarget -Recurse -Force
    }
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $frontDistTarget) -Force)
    Copy-Item -LiteralPath $frontDist -Destination $frontDistTarget -Recurse -Force
}

function New-ZipArchive {
    param(
        [string]$SourceDir,
        [string]$DestinationFile
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $DestinationFile) {
        Remove-Item -LiteralPath $DestinationFile -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $SourceDir,
        $DestinationFile,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}

function New-TarGzArchive {
    param(
        [string]$SourceDir,
        [string]$DestinationFile
    )

    if (Test-Path -LiteralPath $DestinationFile) {
        Remove-Item -LiteralPath $DestinationFile -Force
    }
    Invoke-CheckedCommand -FilePath "tar.exe" -Arguments @("-C", $SourceDir, "-czf", $DestinationFile, ".") -FailureMessage "创建 tar.gz 包失败"
}

function New-ReleaseArchives {
    param([string]$NormalizedVersion)

    Reset-Directory -Path $script:ArtifactsDir
    Reset-Directory -Path $script:StageRoot

    $stageDir = Join-Path $script:StageRoot ("snapshot-{0}" -f $NormalizedVersion)
    [void](New-Item -ItemType Directory -Path $stageDir -Force)
    Copy-TrackedFilesToStage -StageDir $stageDir

    $windowsArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
    $linuxArchive = Join-Path $script:ArtifactsDir ("{0}-linux-x64-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)

    Write-Step "创建 Windows 更新包"
    New-ZipArchive -SourceDir $stageDir -DestinationFile $windowsArchive

    Write-Step "创建 Linux 更新包"
    New-TarGzArchive -SourceDir $stageDir -DestinationFile $linuxArchive

    return [pscustomobject]@{
        WindowsArchive = $windowsArchive
        LinuxArchive = $linuxArchive
    }
}

function Get-ReleaseArchivePaths {
    param([string]$NormalizedVersion)

    return [pscustomobject]@{
        WindowsArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
        LinuxArchive = Join-Path $script:ArtifactsDir ("{0}-linux-x64-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)
    }
}

function Get-ExistingReleaseArchives {
    param([string]$NormalizedVersion)

    $archives = Get-ReleaseArchivePaths -NormalizedVersion $NormalizedVersion
    if (-not (Test-Path -LiteralPath $archives.WindowsArchive)) {
        throw "未找到 Windows 包: $($archives.WindowsArchive)"
    }
    if (-not (Test-Path -LiteralPath $archives.LinuxArchive)) {
        throw "未找到 Linux 包: $($archives.LinuxArchive)"
    }
    return $archives
}

function Get-GitHubTokenFromCredentialHelper {
    $payload = "protocol=https`nhost=github.com`n`n"
    $credentialOutput = $payload | git credential fill 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $values = @{}
    foreach ($line in $credentialOutput) {
        if ($line -match "^(?<key>[^=]+)=(?<value>.*)$") {
            $values[$Matches["key"]] = $Matches["value"]
        }
    }

    $password = [string]($values["password"] ?? "")
    if ([string]::IsNullOrWhiteSpace($password)) {
        return $null
    }
    return $password
}

function Publish-GitHubRelease {
    param(
        [string]$ReleaseTag,
        [string]$Repo,
        [string]$WindowsArchive,
        [string]$LinuxArchive
    )

    $ghCommand = Get-Command gh -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $ghCommand) {
        throw "未找到 gh 命令，请先安装 GitHub CLI。"
    }

    if (-not $env:GH_TOKEN) {
        $helperToken = Get-GitHubTokenFromCredentialHelper
        if ($helperToken) {
            $env:GH_TOKEN = $helperToken
            Write-Info "已从 git credential helper 载入 GitHub 凭据。"
        }
    }

    Write-Step "推送当前提交到 origin"
    Invoke-CheckedCommand -FilePath "git" -Arguments @("push", "origin", $TargetRef) -FailureMessage "推送提交失败"

    Write-Step ("推送 tag {0} 到 origin" -f $ReleaseTag)
    Invoke-CheckedCommand -FilePath "git" -Arguments @("push", "origin", ("refs/tags/{0}" -f $ReleaseTag)) -FailureMessage "推送 tag 失败"

    Write-Step ("创建 GitHub Release {0}" -f $ReleaseTag)
    Invoke-CheckedCommand -FilePath $ghCommand.Source -Arguments @(
        "release",
        "create",
        $ReleaseTag,
        $WindowsArchive,
        $LinuxArchive,
        "--repo", $Repo,
        "--title", $ReleaseTag,
        "--generate-notes",
        "--verify-tag"
    ) -FailureMessage "创建 GitHub Release 失败"
}

try {
    $resolvedMode = Resolve-RequestedMode
    $shouldBuild = $resolvedMode -ne "PublishOnly"
    $shouldPublish = $resolvedMode -ne "BuildOnly"

    Write-Step "检查工作区状态"
    if ($AllowDirtyWorktree) {
        Write-Info "已允许使用当前未提交改动生成本地产物。"
    } else {
        Assert-CleanTrackedWorktree
    }

    Write-Step "校验版本号"
    Assert-VersionMatchesTag
    $normalizedVersion = Normalize-Version $Tag
    Write-Info ("当前模式: {0}" -f $resolvedMode)

    if ($shouldBuild) {
        if (-not $SkipChecks) {
            Invoke-ReleasePrepChecks
        } elseif (-not $SkipBuild) {
            Invoke-BuildOnly
        } else {
            Write-Info "已跳过检查和构建。"
        }

        $archives = New-ReleaseArchives -NormalizedVersion $normalizedVersion
    } else {
        Write-Info "PublishOnly 模式，复用现有产物。"
        $archives = Get-ExistingReleaseArchives -NormalizedVersion $normalizedVersion
    }

    Write-Info ("Windows 包: {0}" -f $archives.WindowsArchive)
    Write-Info ("Linux 包: {0}" -f $archives.LinuxArchive)

    if ($shouldPublish) {
        Ensure-TagAtTarget
        Publish-GitHubRelease -ReleaseTag $Tag -Repo $Repository -WindowsArchive $archives.WindowsArchive -LinuxArchive $archives.LinuxArchive
    } else {
        Write-Info "已跳过 GitHub Release 发布。"
    }

    Write-Host "[完成] 发布流程结束" -ForegroundColor Green
} catch {
    Write-Host ("[错误] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
