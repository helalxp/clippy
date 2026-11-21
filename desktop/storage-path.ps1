function ConvertTo-ClippyPowerShellPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Configured Clippy data directory is empty."
    }

    $normalizedPath = $Path.Trim()
    $wasExtendedPath = $false
    if ($normalizedPath.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        # Win32 extended UNC: \\?\UNC\server\share -> \\server\share
        $wasExtendedPath = $true
        $normalizedPath = '\\' + $normalizedPath.Substring(8)
    } elseif ($normalizedPath.StartsWith('\\?\', [StringComparison]::OrdinalIgnoreCase)) {
        # Win32 extended drive path: \\?\C:\folder -> C:\folder
        $wasExtendedPath = $true
        $normalizedPath = $normalizedPath.Substring(4)
        if ($normalizedPath -notmatch '^[A-Za-z]:\\') {
            throw "Unsupported extended Clippy data path. Choose a drive-letter or UNC folder."
        }
    }

    if ($normalizedPath -notmatch '^[A-Za-z]:\\|^\\\\') {
        throw "Configured Clippy data directory must be an absolute Windows drive or UNC path."
    }

    if ($wasExtendedPath) {
        # Do not strip \\?\ when the path needs it. Windows PowerShell 5.1's
        # FileSystem provider cannot safely Join-Path those extended paths.
        if ($normalizedPath.Length -ge 248) {
            throw "The configured Clippy data directory requires extended-length Windows path support, which this setup step cannot safely join. Choose a shorter data folder."
        }
        foreach ($segment in ($normalizedPath -split '\\')) {
            if ($segment -and ($segment.EndsWith(' ') -or $segment.EndsWith('.'))) {
                throw "The configured Clippy data directory contains a path segment that requires extended-length Windows path support. Choose a folder without trailing dots or spaces."
            }
            if ($segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$') {
                throw "The configured Clippy data directory contains a reserved Windows device name. Choose a different folder name."
            }
        }
    }

    return [IO.Path]::GetFullPath($normalizedPath)
}
