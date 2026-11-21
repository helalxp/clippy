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
    if ($normalizedPath.StartsWith('\\?\UNC\', [StringComparison]::OrdinalIgnoreCase)) {
        # Win32 extended UNC: \\?\UNC\server\share -> \\server\share
        $normalizedPath = '\\' + $normalizedPath.Substring(8)
    } elseif ($normalizedPath.StartsWith('\\?\', [StringComparison]::OrdinalIgnoreCase)) {
        # Win32 extended drive path: \\?\C:\folder -> C:\folder
        $normalizedPath = $normalizedPath.Substring(4)
        if ($normalizedPath -notmatch '^[A-Za-z]:\\') {
            throw "Unsupported extended Clippy data path. Choose a drive-letter or UNC folder."
        }
    }

    if ($normalizedPath -notmatch '^[A-Za-z]:\\|^\\\\') {
        throw "Configured Clippy data directory must be an absolute Windows drive or UNC path."
    }

    return [IO.Path]::GetFullPath($normalizedPath)
}
