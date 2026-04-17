[CmdletBinding()]
param(
    [string]$SourceWorktree,
    [string]$SourceBranch,
    [string]$TargetBranch = "master",
    [switch]$DeleteBranch
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)

    Write-Host ("[信息] {0}" -f $Message)
}

function Write-WarnMessage {
    param([string]$Message)

    Write-Host ("[提示] {0}" -f $Message) -ForegroundColor Yellow
}

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path)
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $normalizedPath = (Resolve-FullPath -Path $Path).TrimEnd("\", "/")
    $normalizedRoot = (Resolve-FullPath -Path $Root).TrimEnd("\", "/")

    if ($normalizedPath.Length -lt $normalizedRoot.Length) {
        return $false
    }

    if (-not $normalizedPath.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }

    if ($normalizedPath.Length -eq $normalizedRoot.Length) {
        return $true
    }

    $nextChar = $normalizedPath[$normalizedRoot.Length]
    return $nextChar -eq "\" -or $nextChar -eq "/"
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory,
        [switch]$AllowFailure
    )

    $output = & git @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if (-not $AllowFailure -and $exitCode -ne 0) {
        $rendered = ($output | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($rendered)) {
            throw ("git {0} 失败，退出码: {1}" -f ($Arguments -join " "), $exitCode)
        }
        throw $rendered
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = @($output)
    }
}

function Get-RepoRoot {
    param([Parameter(Mandatory = $true)][string]$ScriptDir)

    $result = Invoke-Git -Arguments @("-C", $ScriptDir, "rev-parse", "--show-toplevel")
    return (Resolve-FullPath -Path ($result.Output[0].Trim()))
}

function Get-WorktreeEntries {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $result = Invoke-Git -Arguments @("-C", $RepoRoot, "worktree", "list", "--porcelain")
    $entries = @()
    $current = $null

    foreach ($line in $result.Output) {
        $text = [string]$line
        if ([string]::IsNullOrWhiteSpace($text)) {
            if ($null -ne $current) {
                $entries += [pscustomobject]$current
                $current = $null
            }
            continue
        }

        if ($text.StartsWith("worktree ")) {
            if ($null -ne $current) {
                $entries += [pscustomobject]$current
            }
            $current = @{
                Path   = Resolve-FullPath -Path $text.Substring(9).Trim()
                Branch = ""
                Head   = ""
            }
            continue
        }

        if ($null -eq $current) {
            continue
        }

        if ($text.StartsWith("branch refs/heads/")) {
            $current.Branch = $text.Substring(18).Trim()
            continue
        }

        if ($text.StartsWith("HEAD ")) {
            $current.Head = $text.Substring(5).Trim()
        }
    }

    if ($null -ne $current) {
        $entries += [pscustomobject]$current
    }

    return $entries
}

function Get-DirtyStatusLines {
    param([Parameter(Mandatory = $true)][string]$Path)

    $result = Invoke-Git -Arguments @("-C", $Path, "status", "--porcelain", "--untracked-files=all")
    return @($result.Output | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-WorktreeRegistered {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$WorktreePath
    )

    $resolvedPath = Resolve-FullPath -Path $WorktreePath
    $entries = Get-WorktreeEntries -RepoRoot $RepoRoot
    return [bool]($entries | Where-Object { $_.Path -eq $resolvedPath } | Select-Object -First 1)
}

function Remove-WorktreeDirectoryIfLeftover {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    for ($index = 0; $index -lt 3; $index++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        } catch {
            Start-Sleep -Seconds 1
        }

        if (-not (Test-Path -LiteralPath $Path)) {
            return
        }
    }
}

function Remove-WorktreeSafely {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$WorktreePath
    )

    try {
        Invoke-Git -Arguments @("-C", $RepoRoot, "worktree", "remove", $WorktreePath) | Out-Null
    } catch {
        $removeError = $_
        $stillRegistered = Test-WorktreeRegistered -RepoRoot $RepoRoot -WorktreePath $WorktreePath
        if ($stillRegistered) {
            throw $removeError
        }
    }

    Remove-WorktreeDirectoryIfLeftover -Path $WorktreePath

    if (Test-Path -LiteralPath $WorktreePath) {
        throw (
            "Git 已移除 worktree 记录，但目录仍被其它进程占用: {0}`n请关闭占用该目录的终端、编辑器、隧道进程（如 cloudflared）后，再手动删除该空目录。" -f $WorktreePath
        )
    }
}

function Get-StashRefByMessage {
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $result = Invoke-Git -Arguments @("-C", $TargetPath, "stash", "list", "--format=%gd`t%s")
    foreach ($line in $result.Output) {
        $parts = ([string]$line).Split("`t", 2)
        if ($parts.Length -eq 2 -and $parts[1] -eq $Message) {
            return $parts[0]
        }
    }

    return $null
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Get-RepoRoot -ScriptDir $scriptDir
$worktrees = Get-WorktreeEntries -RepoRoot $repoRoot

$resolvedSourceWorktree = $null
if (-not [string]::IsNullOrWhiteSpace($SourceWorktree)) {
    $resolvedSourceWorktree = Resolve-FullPath -Path $SourceWorktree
}

$sourceEntry = $null
if ($resolvedSourceWorktree) {
    $sourceEntry = $worktrees | Where-Object { $_.Path -eq $resolvedSourceWorktree } | Select-Object -First 1
    if (-not $sourceEntry) {
        throw ("未找到对应的 worktree: {0}" -f $resolvedSourceWorktree)
    }
}

if (-not [string]::IsNullOrWhiteSpace($SourceBranch)) {
    $branchEntry = $worktrees | Where-Object { $_.Branch -eq $SourceBranch } | Select-Object -First 1
    if ($resolvedSourceWorktree -and $sourceEntry.Branch -ne $SourceBranch) {
        throw "SourceWorktree 与 SourceBranch 不匹配。"
    }
    if (-not $sourceEntry) {
        $sourceEntry = $branchEntry
    }
}

if (-not $sourceEntry) {
    throw "请通过 -SourceWorktree 或 -SourceBranch 指定待合并的 worktree。"
}

if ([string]::IsNullOrWhiteSpace($sourceEntry.Branch)) {
    throw "源 worktree 没有关联本地分支，无法自动合并。"
}

if ($sourceEntry.Branch -eq $TargetBranch) {
    throw "源分支与目标分支相同，无法执行合并。"
}

$targetEntry = $worktrees | Where-Object { $_.Branch -eq $TargetBranch } | Select-Object -First 1
if (-not $targetEntry) {
    throw ("未找到检出目标分支 {0} 的 worktree。" -f $TargetBranch)
}

$currentLocation = Resolve-FullPath -Path (Get-Location).ProviderPath
if (Test-PathInside -Path $currentLocation -Root $sourceEntry.Path) {
    throw ("当前目录位于待删除的 worktree 内: {0}。请切换到主仓库或其它目录后再运行。" -f $sourceEntry.Path)
}

$sourceDirty = Get-DirtyStatusLines -Path $sourceEntry.Path
if ($sourceDirty.Count -gt 0) {
    throw ("源 worktree 存在未提交改动，无法安全合并。请先提交或暂存:`n{0}" -f ($sourceDirty -join "`n"))
}

$targetDirty = Get-DirtyStatusLines -Path $targetEntry.Path
$stashRef = $null
$stashMessage = $null

try {
    if ($targetDirty.Count -gt 0) {
        $stashMessage = "auto-merge-worktree:{0}->{1}:{2}" -f $sourceEntry.Branch, $TargetBranch, [DateTimeOffset]::Now.ToUnixTimeSeconds()
        Write-WarnMessage ("目标分支 worktree 有未提交改动，准备暂存后再合并: {0}" -f $targetEntry.Path)
        Invoke-Git -Arguments @("-C", $targetEntry.Path, "stash", "push", "--include-untracked", "-m", $stashMessage) | Out-Null
        $stashRef = Get-StashRefByMessage -TargetPath $targetEntry.Path -Message $stashMessage
        if (-not $stashRef) {
            Write-WarnMessage "未创建 stash，可能只有文件时间戳变化。继续执行合并。"
        } else {
            Write-Info ("已保存目标分支本地改动: {0}" -f $stashRef)
        }
    }

    Write-Info ("正在将 {0} 合并到 {1}" -f $sourceEntry.Branch, $TargetBranch)
    Invoke-Git -Arguments @("-C", $targetEntry.Path, "merge", "--no-edit", $sourceEntry.Branch) | Out-Null

    Write-Info ("正在删除 worktree: {0}" -f $sourceEntry.Path)
    Remove-WorktreeSafely -RepoRoot $repoRoot -WorktreePath $sourceEntry.Path
    Invoke-Git -Arguments @("-C", $repoRoot, "worktree", "prune") | Out-Null

    if ($DeleteBranch) {
        Write-Info ("正在删除已合并的本地分支: {0}" -f $sourceEntry.Branch)
        Invoke-Git -Arguments @("-C", $targetEntry.Path, "branch", "-d", $sourceEntry.Branch) | Out-Null
    }

    if ($stashRef) {
        Write-Info ("正在恢复目标分支原有未提交改动: {0}" -f $stashRef)
        Invoke-Git -Arguments @("-C", $targetEntry.Path, "stash", "apply", $stashRef) | Out-Null
        Invoke-Git -Arguments @("-C", $targetEntry.Path, "stash", "drop", $stashRef) | Out-Null
    }
} catch {
    if ($stashRef) {
        Write-WarnMessage ("目标分支原有改动仍保存在 {0}，如需手动恢复请执行: git -C `"{1}`" stash apply {0}" -f $stashRef, $targetEntry.Path)
    }
    throw
}

Write-Host ""
Write-Info ("合并完成: {0} -> {1}" -f $sourceEntry.Branch, $TargetBranch)
Write-Info ("目标 worktree: {0}" -f $targetEntry.Path)
Write-Info ("已删除 worktree: {0}" -f $sourceEntry.Path)
