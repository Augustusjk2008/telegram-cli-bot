param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$Sha256,
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [string]$Python = "",
    [string]$PreviousPython = "",
    [string]$BaselinePackage = "",
    [string]$BaselineSha256 = "",
    [string]$HealthUrl = "",
    [switch]$Apply,
    [switch]$HostStopped
)
$ErrorActionPreference = "Stop"
if (-not $Python) {
    $embeddedPython = Join-Path $RepoRoot "runtime/python/python.exe"
    $Python = if (Test-Path -LiteralPath $embeddedPython) { $embeddedPython } else { (Get-Command python -ErrorAction Stop).Source }
}
$bootstrap = Join-Path $PSScriptRoot "update_bootstrap.py"
$arguments = @($bootstrap, "--repo-root", $RepoRoot, "--package", $Package, "--sha256", $Sha256,
               "--work-dir", $WorkDir, "--extract-only")
if ($PreviousPython) { $arguments += @("--previous-python", $PreviousPython) }
if ($BaselinePackage) { $arguments += @("--baseline-package", $BaselinePackage, "--baseline-sha256", $BaselineSha256) }
if ($HealthUrl) { $arguments += @("--health-url", $HealthUrl) }
if ($Apply) { $arguments += "--apply" }
if ($HostStopped) { $arguments += "--host-stopped" }
# This extraction process exits before the new portable runtime starts replacing files.
$output = & $Python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$handoff = ($output -join "`n") | ConvertFrom-Json
$command = @($handoff.command)
& $command[0] @($command[1..($command.Length - 1)])
exit $LASTEXITCODE
