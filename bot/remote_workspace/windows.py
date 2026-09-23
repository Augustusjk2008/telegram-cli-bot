"""Windows PowerShell scripts for SSH targets, including Windows 7 with WMF 5.1.

Scripts use Windows PowerShell syntax and .NET Framework APIs, not PowerShell 7.
Only a small ASCII bootstrap travels through the SSH server's default shell;
noninteractive scripts are sent as UTF-8 stdin to avoid cmd.exe's command limit.
"""
from __future__ import annotations

import base64


def literal(value: str) -> str:
    # PowerShell also treats typographic quotes as delimiters. Keep all path
    # data outside its parser, including names containing curly apostrophes.
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))"


def native_path(path: str) -> str:
    return path.lstrip("/").replace("/", "\\")


_ENCODING = """$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PSVersionTable.PSVersion -lt [Version]'5.1' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Windows PowerShell 5.1 is required'
}
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $OutputEncoding
[Console]::OutputEncoding = $OutputEncoding
"""


def encoded_command(script: str, *, interactive: bool = False) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    mode = "-NoExit" if interactive else "-NonInteractive"
    return f"powershell.exe -NoLogo -NoProfile -OutputFormat Text {mode} -EncodedCommand {encoded}"


STDIN_COMMAND = encoded_command(_ENCODING + """try {
    & ([ScriptBlock]::Create([Console]::In.ReadToEnd()))
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
""")


def batch(commands: list[str]) -> str:
    # PowerShell 5.1 does not turn a native program's nonzero exit into an error.
    # Dot sourcing retains variables and directory changes between batch items.
    return "\n".join(
        "$global:LASTEXITCODE = 0\n. {\n" + command + "\n}\n"
        "if (-not $?) { if ($LASTEXITCODE) { exit $LASTEXITCODE }; exit 1 }\n"
        "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
        for command in commands
    )


def command_script(command: str, directory: str) -> str:
    return (_ENCODING + "Set-Location -LiteralPath " + literal(native_path(directory)) + "\n"
            + batch([command]) + "\nexit 0\n")


def terminal_command(directory: str) -> str:
    return encoded_command(_ENCODING + "Set-Location -LiteralPath " + literal(native_path(directory)), interactive=True)


_FILE_HELPERS = """
function Assert-OrbitPath([string]$path, [bool]$missing) {
    $drive = [IO.Path]::GetPathRoot($path)
    $parts = $path.Substring($drive.Length).Split([char]'\\')
    $current = $drive
    for ($index = -1; $index -lt $parts.Length; $index++) {
        if ($index -ge 0) {
            if ($parts[$index] -eq '') { continue }
            $current = [IO.Path]::Combine($current, $parts[$index])
        }
        try { $attributes = [IO.File]::GetAttributes($current) }
        catch [IO.FileNotFoundException] {
            if ($missing -and $index -eq $parts.Length - 1) { return }
            throw 'path_not_found'
        }
        catch [IO.DirectoryNotFoundException] { throw 'path_not_found' }
        if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'forbidden_path'
        }
    }
}
"""


def file_script(paths: list[str], *, missing: bool = False, action: str = "check",
                temporary: str = "", exists: bool = False, version: str | None = None) -> str:
    """Guard against junctions/symlinks and safely prepare or commit a staged file.

Windows SFTP realpath alone is insufficient to enforce the selected root.
Reparse points are deliberately unavailable in Windows file APIs. Commands and
terminals, as on POSIX, still have the SSH account's normal filesystem access.
"""
    script = _ENCODING + _FILE_HELPERS + "\ntry {\n"
    for path in paths:
        script += f"Assert-OrbitPath {literal(native_path(path))} ${str(missing).lower()}\n"
    if action != "check":
        target = literal(native_path(paths[-1]))
        source = literal(native_path(temporary))
        script += f"Assert-OrbitPath {source} $false\n"
        if action == "prepare" and exists:
            # A loaded FileSecurity has no modified sections; copying it
            # directly would leave the staging file's inherited DACL intact.
            script += "$acl = New-Object Security.AccessControl.FileSecurity\n"
            script += f"$acl.SetSecurityDescriptorBinaryForm([IO.File]::GetAccessControl({target}).GetSecurityDescriptorBinaryForm(), [Security.AccessControl.AccessControlSections]::Access)\n"
            script += f"[IO.File]::SetAccessControl({source}, $acl)\n"
        elif action == "commit":
            if version is not None:
                script += f"""$stream = [IO.File]::OpenRead({target})
try {{
    $hash = [Security.Cryptography.SHA256]::Create()
    try {{ $digest = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }}
    finally {{ $hash.Dispose() }}
}} finally {{ $stream.Dispose() }}
if (('sha256:' + $digest) -ne {literal(version)}) {{ throw 'file_version_conflict' }}
"""
            if exists:
                backup = literal(native_path(temporary) + ".bak")
                script += f"Assert-OrbitPath {backup} $true\n"
                script += f"if ([IO.File]::Exists({backup}) -or [IO.Directory]::Exists({backup})) {{ throw 'path_exists' }}\n"
                script += f"[IO.File]::Replace({source}, {target}, {backup}, $false)\n"
                script += f"try {{ [IO.File]::Delete({backup}) }} catch {{ }}\n"
            else:
                script += f"if ([IO.File]::Exists({target}) -or [IO.Directory]::Exists({target})) {{ throw 'path_exists' }}\n"
                script += f"[IO.File]::Move({source}, {target})\n"
    return script + """} catch {
    $code = $_.Exception.Message
    $cause = $_.Exception
    while ($cause.InnerException) { $cause = $cause.InnerException }
    if ($cause -is [UnauthorizedAccessException]) { $code = 'permission_denied' }
    if ($cause -is [IO.PathTooLongException]) { $code = 'invalid_path' }
    if ($code -notin @('forbidden_path', 'path_not_found', 'path_exists', 'file_version_conflict', 'permission_denied', 'invalid_path')) {
        $code = 'remote_io_error'
    }
    [Console]::Error.WriteLine('ORBIT:' + $code)
    exit 1
}
exit 0
"""
