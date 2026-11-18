[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ReleaseTag,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$SignaturePath,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$ReleaseNotesPath,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$version = $ReleaseTag -replace '^v', ''
if ($version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$') {
    throw "Release tag '$ReleaseTag' does not contain a valid SemVer version."
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "Repository must be in owner/name format."
}

$installer = Get-Item -LiteralPath $InstallerPath
$signature = (Get-Content -LiteralPath $SignaturePath -Raw -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($signature)) {
    throw "Tauri updater signature is empty: $SignaturePath"
}

$notes = Get-Content -LiteralPath $ReleaseNotesPath -Raw -Encoding UTF8
$escapedAssetName = [System.Uri]::EscapeDataString($installer.Name)
$installerUrl = "https://github.com/$Repository/releases/download/$ReleaseTag/$escapedAssetName"

$manifest = [ordered]@{
    version = $version
    notes = $notes
    pub_date = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    platforms = [ordered]@{
        "windows-x86_64" = [ordered]@{
            signature = $signature
            url = $installerUrl
        }
    }
}

$manifestDirectory = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($manifestDirectory)) {
    New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null
}
$json = $manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($OutputPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

# Read the serialized file back so malformed JSON or accidental field loss fails the release.
$verified = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($verified.version -ne $version -or
    $verified.platforms.'windows-x86_64'.url -ne $installerUrl -or
    $verified.platforms.'windows-x86_64'.signature -ne $signature) {
    throw "Generated updater manifest did not pass its self-validation."
}

Write-Host "Generated signed Windows updater manifest for Clippy $version."
