param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Repository = "Augustusjk2008/telegram-cli-bot",
    [string]$ReleaseBranch = "master",
    [string]$ReleaseNotesFile = "",
    [ValidateSet("BuildAndPublish", "BuildOnly", "PublishOnly")]
    [string]$Mode = "BuildAndPublish",
    [switch]$RunChecks,
    [switch]$AllowDirtyWorktree,
    [switch]$AutoConfirmDirtyWorktree,
    [switch]$SkipWindowsPortable
)

$ErrorActionPreference = "Stop"

$script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script:RepoRoot = Split-Path -Parent $script:ScriptDir
$script:ArtifactsDir = Join-Path $script:ScriptDir "artifacts"
$script:StageRoot = Join-Path $script:ScriptDir "stage"
$script:PortableBuildScript = Join-Path $script:ScriptDir "portable-win\build-portable.ps1"
$script:FrontDir = Join-Path $script:RepoRoot "front"
$script:VersionFile = Join-Path $script:RepoRoot "VERSION"
$script:PackageBaseName = "orbit-safe-claw"

function Write-Step {
    param([string]$Message)

    Write-Host ("[步骤] {0}" -f $Message) -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)

    Write-Host ("[信息] {0}" -f $Message)
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

    $originalLocation = Get-Location
    try {
        Set-Location $script:RepoRoot
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        Set-Location $originalLocation
    }

    if ($exitCode -ne 0) {
        $detail = ($output | Out-String).Trim()
        if ($detail) {
            throw "{0}: {1}" -f $FailureMessage, $detail
        }
        throw $FailureMessage
    }
    return @($output)
}

function Invoke-GitResult {
    param([string[]]$Arguments)

    $originalLocation = Get-Location
    try {
        Set-Location $script:RepoRoot
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        Set-Location $originalLocation
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output)
    }
}

function Normalize-Version {
    param([string]$Value)

    $text = [string]::IsNullOrWhiteSpace($Value) ? "" : $Value.Trim()
    if ($text.StartsWith("v")) {
        return $text.Substring(1)
    }
    return $text
}

function Assert-ValidVersion {
    param([string]$Value)

    if ($Value -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') {
        throw "版本号格式无效: $Value。请使用如 1.0.3 或 1.0.3-beta.1。"
    }
}

function Normalize-ReleaseBranch {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "master"
    }
    return $Value.Trim()
}

function Assert-ValidReleaseBranch {
    param([string]$Value)

    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value -notmatch '^[-0-9A-Za-z._/]+$' -or
        $Value.Contains("..") -or
        $Value.Contains("//") -or
        $Value.Contains("@{") -or
        $Value.StartsWith("/") -or
        $Value.EndsWith("/") -or
        $Value.EndsWith(".") -or
        $Value.EndsWith(".lock")
    ) {
        throw "发布分支名称无效: $Value"
    }
}

function Normalize-GitHubRepository {
    param([string]$Value)

    $text = [string]::IsNullOrWhiteSpace($Value) ? "" : $Value.Trim()
    $patterns = @(
        '^https://github\.com/(?<owner>[^/\s]+)/(?<repo>[^/\s]+?)(?:\.git)?/?$',
        '^ssh://git@github\.com/(?<owner>[^/\s]+)/(?<repo>[^/\s]+?)(?:\.git)?$',
        '^git@github\.com:(?<owner>[^/\s]+)/(?<repo>[^/\s]+?)(?:\.git)?$',
        '^(?<owner>[^/\s]+)/(?<repo>[^/\s]+?)(?:\.git)?$'
    )

    foreach ($pattern in $patterns) {
        if ($text -match $pattern) {
            return "{0}/{1}" -f $Matches["owner"], $Matches["repo"]
        }
    }

    throw "GitHub 仓库格式无效: $Value"
}

function Assert-OriginMatchesRepository {
    param([string]$ExpectedRepository)

    $fetchUrl = (Invoke-Git -Arguments @("remote", "get-url", "origin") -FailureMessage "读取 origin fetch URL 失败" | Select-Object -First 1).Trim()
    $pushUrl = (Invoke-Git -Arguments @("remote", "get-url", "--push", "origin") -FailureMessage "读取 origin push URL 失败" | Select-Object -First 1).Trim()
    $fetchRepository = Normalize-GitHubRepository $fetchUrl
    $pushRepository = Normalize-GitHubRepository $pushUrl

    if (-not [string]::Equals($fetchRepository, $ExpectedRepository, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "origin fetch URL 指向 $fetchRepository，但发布仓库为 $ExpectedRepository。"
    }
    if (-not [string]::Equals($pushRepository, $ExpectedRepository, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "origin push URL 指向 $pushRepository，但发布仓库为 $ExpectedRepository。"
    }
}

function Get-AppVersion {
    if (-not (Test-Path -LiteralPath $script:VersionFile)) {
        throw "未找到版本文件: $script:VersionFile"
    }
    $value = (Get-Content -LiteralPath $script:VersionFile -Raw -Encoding UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "版本文件为空: $script:VersionFile"
    }
    return $value
}

function Set-AppVersion {
    param([string]$NormalizedVersion)

    Set-Content -LiteralPath $script:VersionFile -Value $NormalizedVersion -Encoding UTF8
}

function Resolve-ReleaseNotesFile {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }

    $candidate = $PathText
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $script:RepoRoot $candidate
    }

    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "未找到 Release Notes 文件: $candidate"
    }

    return (Resolve-Path -LiteralPath $candidate).ProviderPath
}

function Get-WorktreeStatus {
    param(
        [switch]$TrackedOnly
    )

    $arguments = @("status", "--short")
    if ($TrackedOnly) {
        $arguments += "--untracked-files=no"
    }

    $status = Invoke-Git -Arguments $arguments -FailureMessage "无法读取 git 状态。"
    return @($status | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Assert-ReleaseBranch {
    param(
        [string]$ExpectedBranch,
        [string]$ExpectedRepository
    )

    Write-Step ("校验发布分支 {0}" -f $ExpectedBranch)
    Assert-OriginMatchesRepository -ExpectedRepository $ExpectedRepository

    $currentBranch = (Invoke-Git -Arguments @("rev-parse", "--abbrev-ref", "HEAD") -FailureMessage "读取当前分支失败" | Select-Object -First 1).Trim()
    if ($currentBranch -eq "HEAD") {
        throw "当前处于 detached HEAD，不能发布。"
    }
    if ($currentBranch -ne $ExpectedBranch) {
        throw "当前分支为 $currentBranch，发布分支必须为 $ExpectedBranch。"
    }

    $remoteRef = "refs/remotes/origin/$ExpectedBranch"
    $fetchRefspec = "+refs/heads/{0}:{1}" -f $ExpectedBranch, $remoteRef
    Invoke-CheckedCommand -FilePath "git" -Arguments @("fetch", "--tags", "origin", $fetchRefspec) -FailureMessage "拉取发布分支状态失败"

    $remoteCheck = Invoke-GitResult -Arguments @("show-ref", "--verify", "--quiet", $remoteRef)
    if ($remoteCheck.ExitCode -ne 0) {
        throw "未找到远端发布分支 origin/$ExpectedBranch。"
    }

    $ancestorCheck = Invoke-GitResult -Arguments @("merge-base", "--is-ancestor", "origin/$ExpectedBranch", "HEAD")
    if ($ancestorCheck.ExitCode -ne 0) {
        throw "当前分支不包含 origin/$ExpectedBranch，请先同步远端发布分支。"
    }

    Write-Info ("发布分支已校验: {0}" -f $ExpectedBranch)
}

function Assert-CleanTrackedWorktree {
    $status = Get-WorktreeStatus -TrackedOnly
    if (($status | Out-String).Trim()) {
        throw "存在未提交的 tracked 改动，请先提交后再生成本地产物，或显式使用 -AllowDirtyWorktree。"
    }
}

function Confirm-DirtyWorktreeForPublish {
    param(
        [string[]]$StatusLines,
        [string]$NormalizedVersion
    )

    if (-not (($StatusLines | Out-String).Trim())) {
        return
    }

    Write-Host "[警告] 检测到未提交改动，发布时将与版本号一起自动提交当前工作区：" -ForegroundColor Yellow
    foreach ($line in $StatusLines) {
        Write-Host ("  {0}" -f $line) -ForegroundColor Yellow
    }

    if ($AutoConfirmDirtyWorktree) {
        Write-Info ("已启用 -AutoConfirmDirtyWorktree，将在发布检查后提交当前工作区并继续发布 {0}。" -f $NormalizedVersion)
        return
    }

    $answer = Read-Host ("是否在发布检查后提交当前工作区并继续发布 {0}？输入 y 确认" -f $NormalizedVersion)
    if ($answer -notmatch "^(?i:y|yes)$") {
        throw "已取消发布。"
    }
}

function Sync-VersionFile {
    param([string]$NormalizedVersion)

    $currentVersion = Get-AppVersion
    if ($currentVersion -eq $NormalizedVersion) {
        Write-Info ("版本号已是 {0}" -f $NormalizedVersion)
        return $false
    }

    Write-Step ("更新版本号到 {0}" -f $NormalizedVersion)
    Set-AppVersion -NormalizedVersion $NormalizedVersion
    return $true
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
        "tests/test_runtime_web_startup.py",
        "tests/test_runtime_paths.py",
        "tests/test_updater.py",
        "tests/test_web_api.py",
        "tests/test_release_assets.py",
        "tests/test_native_agent_config.py",
        "tests/test_native_agent.py",
        "tests/test_pi_rpc_client.py",
        "tests/test_pi_windows_preflight.py",
        "-q"
    ) -FailureMessage "后端发布检查失败"

    Write-Step "运行前端发布检查"
    Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @(
        "test",
        "--",
        "--run",
        "src/test/settings-screen.test.tsx",
        "src/test/chat-screen.test.tsx",
        "src/test/real-client.test.ts"
    ) -FailureMessage "前端发布检查失败" -WorkingDirectory $script:FrontDir
}

function Invoke-FrontBuild {
    param([string]$StepMessage = "构建前端")

    Write-Step $StepMessage
    Invoke-CheckedCommand -FilePath "npm.cmd" -Arguments @("run", "build") -FailureMessage "前端构建失败" -WorkingDirectory $script:FrontDir
}

function Invoke-PostPortableFrontBuild {
    Write-Info "Windows 绿色版构建会临时使用根路径资源，正在恢复本机前端构建产物。"
    Invoke-FrontBuild -StepMessage "恢复本机前端构建产物"
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

function Write-DistributionMarker {
    param(
        [string]$Root,
        [string]$PackageKind,
        [string]$Platform,
        [string]$Version
    )

    $payload = [ordered]@{
        packageKind = $PackageKind
        platform = $Platform
        version = $Version
    } | ConvertTo-Json
    Set-Content -LiteralPath (Join-Path $Root ".distribution.json") -Value $payload -Encoding UTF8
}

function New-Sha256File {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    $checksumPath = "$Path.sha256"
    $line = "{0}  {1}" -f $hash, (Split-Path -Leaf $Path)
    Set-Content -LiteralPath $checksumPath -Value $line -Encoding ASCII
    return $checksumPath
}

function New-ArchiveChecksumFiles {
    param($Archives)
    $checksums = @()
    foreach ($archive in @($Archives.WindowsArchive, $Archives.WindowsInstallerArchive, $Archives.LinuxArchive, $Archives.MacOSArchive)) {
        $checksum = New-Sha256File -Path $archive
        if (-not [string]::IsNullOrWhiteSpace($checksum)) {
            $checksums += $checksum
        }
    }
    return $checksums
}

function New-ReleaseArchives {
    param([string]$NormalizedVersion)

    Reset-Directory -Path $script:ArtifactsDir
    Reset-Directory -Path $script:StageRoot

    $stageDir = Join-Path $script:StageRoot ("snapshot-{0}" -f $NormalizedVersion)
    [void](New-Item -ItemType Directory -Path $stageDir -Force)
    Copy-TrackedFilesToStage -StageDir $stageDir

    $windowsPortableArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
    $windowsInstallerArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-installer-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
    $linuxArchive = Join-Path $script:ArtifactsDir ("{0}-linux-x64-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)
    $macosArchive = Join-Path $script:ArtifactsDir ("{0}-macos-universal-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)

    if ($SkipWindowsPortable) {
        Write-Info "已跳过 Windows 绿色版包"
        $windowsPortableArchive = $null
    } else {
        Write-Step "创建 Windows 绿色版包"
        $portableBuildSucceeded = $false
        try {
            Invoke-CheckedCommand -FilePath "powershell.exe" -Arguments @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", $script:PortableBuildScript,
                "-PackageName", ("{0}-windows-x64-{1}" -f $script:PackageBaseName, $NormalizedVersion),
                "-ArtifactPath", $windowsPortableArchive
            ) -FailureMessage "创建 Windows 绿色版包失败"
            $portableBuildSucceeded = $true
        } finally {
            try {
                Invoke-PostPortableFrontBuild
            } catch {
                if ($portableBuildSucceeded) {
                    throw
                }
                Write-Host ("[错误] 恢复本机前端构建产物失败: {0}" -f $_.Exception.Message) -ForegroundColor Red
            }
        }
    }

    Write-Step "创建 Windows 安装版包"
    Write-DistributionMarker -Root $stageDir -PackageKind "installer" -Platform "windows-x64" -Version $NormalizedVersion
    New-ZipArchive -SourceDir $stageDir -DestinationFile $windowsInstallerArchive

    Write-Step "创建 Linux 更新包"
    Write-DistributionMarker -Root $stageDir -PackageKind "linux" -Platform "linux-x64" -Version $NormalizedVersion
    New-TarGzArchive -SourceDir $stageDir -DestinationFile $linuxArchive

    Write-Step "创建 macOS 更新包"
    Write-DistributionMarker -Root $stageDir -PackageKind "macos" -Platform "macos-universal" -Version $NormalizedVersion
    New-TarGzArchive -SourceDir $stageDir -DestinationFile $macosArchive

    return [pscustomobject]@{
        WindowsArchive = $windowsPortableArchive
        WindowsInstallerArchive = $windowsInstallerArchive
        LinuxArchive = $linuxArchive
        MacOSArchive = $macosArchive
    }
}

function Get-ReleaseArchivePaths {
    param([string]$NormalizedVersion)

    return [pscustomobject]@{
        WindowsArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
        WindowsInstallerArchive = Join-Path $script:ArtifactsDir ("{0}-windows-x64-installer-{1}.zip" -f $script:PackageBaseName, $NormalizedVersion)
        LinuxArchive = Join-Path $script:ArtifactsDir ("{0}-linux-x64-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)
        MacOSArchive = Join-Path $script:ArtifactsDir ("{0}-macos-universal-{1}.tar.gz" -f $script:PackageBaseName, $NormalizedVersion)
    }
}

function Get-ExistingReleaseArchives {
    param([string]$NormalizedVersion)

    $archives = Get-ReleaseArchivePaths -NormalizedVersion $NormalizedVersion
    if ($SkipWindowsPortable) {
        $archives.WindowsArchive = $null
    } elseif (-not (Test-Path -LiteralPath $archives.WindowsArchive)) {
        throw "未找到 Windows 绿色版包: $($archives.WindowsArchive)"
    }
    if (-not (Test-Path -LiteralPath $archives.WindowsInstallerArchive)) {
        throw "未找到 Windows 安装版包: $($archives.WindowsInstallerArchive)"
    }
    if (-not (Test-Path -LiteralPath $archives.LinuxArchive)) {
        throw "未找到 Linux 包: $($archives.LinuxArchive)"
    }
    if (-not (Test-Path -LiteralPath $archives.MacOSArchive)) {
        throw "未找到 macOS 包: $($archives.MacOSArchive)"
    }
    return $archives
}

function Commit-ReleaseChanges {
    param([string]$NormalizedVersion)

    $status = Get-WorktreeStatus
    if (-not (($status | Out-String).Trim())) {
        Write-Info "工作区无待提交改动，继续沿用当前 HEAD。"
        return
    }

    $commitMessage = "chore: release $NormalizedVersion"

    Write-Step "提交发布改动"
    Invoke-CheckedCommand -FilePath "git" -Arguments @("add", "-A") -FailureMessage "暂存发布改动失败"
    Invoke-CheckedCommand -FilePath "git" -Arguments @("commit", "-m", $commitMessage) -FailureMessage "提交发布改动失败"
}

function Ensure-TagAtHead {
    param([string]$ReleaseTag)

    $headCommit = (Invoke-Git -Arguments @("rev-parse", "HEAD") -FailureMessage "读取 HEAD 失败" | Select-Object -First 1).Trim()
    $existingTagResult = Invoke-GitResult -Arguments @("rev-parse", "-q", "--verify", ("refs/tags/{0}" -f $ReleaseTag))
    $existingTag = ($existingTagResult.Output | Select-Object -First 1)
    if ($existingTagResult.ExitCode -eq 0 -and $existingTag) {
        $tagCommit = (Invoke-Git -Arguments @("rev-list", "-n", "1", $ReleaseTag) -FailureMessage "读取 tag 提交失败" | Select-Object -First 1).Trim()
        if ($tagCommit -ne $headCommit) {
            throw "tag $ReleaseTag 已存在，但不指向当前 HEAD。"
        }
        Write-Info ("tag 已存在并指向当前 HEAD: {0}" -f $ReleaseTag)
        return
    }

    Write-Step ("创建 tag {0}" -f $ReleaseTag)
    Invoke-CheckedCommand -FilePath "git" -Arguments @("tag", "-a", $ReleaseTag, "HEAD", "-m", ("Release {0}" -f $ReleaseTag)) -FailureMessage "创建 tag 失败"
}

function Get-GitHubTokenFromCredentialHelper {
    $payload = "protocol=https`nhost=github.com`n`n"
    $previousTerminalPrompt = $env:GIT_TERMINAL_PROMPT
    $previousGcmInteractive = $env:GCM_INTERACTIVE
    try {
        $env:GIT_TERMINAL_PROMPT = "0"
        $env:GCM_INTERACTIVE = "Never"
        $credentialOutput = $payload | git -c credential.interactive=false credential fill 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
    } finally {
        $env:GIT_TERMINAL_PROMPT = $previousTerminalPrompt
        $env:GCM_INTERACTIVE = $previousGcmInteractive
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
        [string]$WindowsInstallerArchive,
        [string]$LinuxArchive,
        [string]$MacOSArchive,
        [string[]]$ChecksumArchives,
        [string]$ReleaseNotesFile,
        [string]$ReleaseBranch
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

    Write-Step "推送当前分支到 origin"
    Invoke-CheckedCommand -FilePath "git" -Arguments @("push", "origin", ("HEAD:refs/heads/{0}" -f $ReleaseBranch)) -FailureMessage "推送分支失败"

    Write-Step ("推送 tag {0} 到 origin" -f $ReleaseTag)
    Invoke-CheckedCommand -FilePath "git" -Arguments @("push", "origin", ("refs/tags/{0}" -f $ReleaseTag)) -FailureMessage "推送 tag 失败"

    $releaseAssets = @()
    if (-not [string]::IsNullOrWhiteSpace($WindowsArchive)) {
        $releaseAssets += $WindowsArchive
    }
    $releaseAssets += @($WindowsInstallerArchive, $LinuxArchive, $MacOSArchive)
    if ($ChecksumArchives) {
        $releaseAssets += $ChecksumArchives
    }

    Write-Step ("创建 GitHub Release {0}" -f $ReleaseTag)
    $releaseArguments = @(
        "release",
        "create",
        $ReleaseTag
    ) + $releaseAssets + @(
        "--repo", $Repo,
        "--title", $ReleaseTag,
        "--verify-tag"
    )

    if (-not [string]::IsNullOrWhiteSpace($ReleaseNotesFile)) {
        Write-Info ("GitHub Release body: {0}" -f $ReleaseNotesFile)
        $releaseArguments += @("--notes-file", $ReleaseNotesFile)
    } else {
        $releaseArguments += "--generate-notes"
    }

    Invoke-CheckedCommand -FilePath $ghCommand.Source -Arguments $releaseArguments -FailureMessage "创建 GitHub Release 失败"
}

try {
    $normalizedVersion = Normalize-Version $Version
    Assert-ValidVersion -Value $normalizedVersion
    $normalizedRepository = Normalize-GitHubRepository $Repository
    $normalizedReleaseBranch = Normalize-ReleaseBranch $ReleaseBranch
    Assert-ValidReleaseBranch -Value $normalizedReleaseBranch
    $releaseTag = "v$normalizedVersion"
    $shouldBuild = $Mode -ne "PublishOnly"
    $shouldPublish = $Mode -ne "BuildOnly"
    $releaseNotesPath = ""
    $worktreeStatus = @()

    if ($shouldPublish) {
        Assert-ReleaseBranch -ExpectedBranch $normalizedReleaseBranch -ExpectedRepository $normalizedRepository
    }

    Write-Step "检查工作区状态"
    if ($shouldPublish) {
        $worktreeStatus = Get-WorktreeStatus
        if (-not $shouldBuild -and (($worktreeStatus | Out-String).Trim())) {
            throw "PublishOnly 模式复用现有产物，不支持 dirty worktree；请先提交改动，或使用 BuildAndPublish 重新生成发布包。"
        }
        Confirm-DirtyWorktreeForPublish -StatusLines $worktreeStatus -NormalizedVersion $normalizedVersion
    } elseif ($AllowDirtyWorktree) {
        Write-Info "已允许使用当前未提交改动生成本地产物。"
    } else {
        Assert-CleanTrackedWorktree
    }

    Write-Step ("准备版本 {0}" -f $normalizedVersion)
    if ($shouldBuild) {
        [void](Sync-VersionFile -NormalizedVersion $normalizedVersion)
    } else {
        $currentVersion = Get-AppVersion
        if ($currentVersion -ne $normalizedVersion) {
            throw "PublishOnly 模式要求 VERSION 当前即为 $normalizedVersion，当前值为 $currentVersion。"
        }
    }

    Write-Info ("当前模式: {0}" -f $Mode)
    if ($shouldBuild) {
        if ($RunChecks) {
            Invoke-ReleasePrepChecks
        } else {
            Write-Info "已跳过发布前测试检查。"
        }

        Invoke-FrontBuild
    } else {
        Write-Info "PublishOnly 模式，复用现有产物。"
    }

    if ($shouldPublish) {
        $releaseNotesPath = Resolve-ReleaseNotesFile -PathText $ReleaseNotesFile
        Commit-ReleaseChanges -NormalizedVersion $normalizedVersion
    }

    if ($shouldBuild) {
        $archives = New-ReleaseArchives -NormalizedVersion $normalizedVersion
    } else {
        $archives = Get-ExistingReleaseArchives -NormalizedVersion $normalizedVersion
    }

    if ($archives.WindowsArchive) {
        Write-Info ("Windows 绿色版包: {0}" -f $archives.WindowsArchive)
    } else {
        Write-Info "Windows 绿色版包: 已跳过"
    }
    Write-Info ("Windows 安装版包: {0}" -f $archives.WindowsInstallerArchive)
    Write-Info ("Linux 包: {0}" -f $archives.LinuxArchive)
    Write-Info ("macOS 包: {0}" -f $archives.MacOSArchive)
    $checksumArchives = New-ArchiveChecksumFiles -Archives $archives

    if ($shouldPublish) {
        Ensure-TagAtHead -ReleaseTag $releaseTag
        Publish-GitHubRelease -ReleaseTag $releaseTag -Repo $normalizedRepository -WindowsArchive $archives.WindowsArchive -WindowsInstallerArchive $archives.WindowsInstallerArchive -LinuxArchive $archives.LinuxArchive -MacOSArchive $archives.MacOSArchive -ChecksumArchives $checksumArchives -ReleaseNotesFile $releaseNotesPath -ReleaseBranch $normalizedReleaseBranch
    } else {
        Write-Info "已跳过 GitHub Release 发布。"
    }

    Write-Host "[完成] 发布流程结束" -ForegroundColor Green
} catch {
    Write-Host ("[错误] {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
