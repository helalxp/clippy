[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version = "",

    [switch]$Check,

    # Test hook: lets Pester exercise the real script against an isolated fixture tree.
    [string]$RootPath = ""
)

$ErrorActionPreference = "Stop"

if ($Check -and -not [string]::IsNullOrWhiteSpace($Version)) {
    throw "Do not pass a version value together with -Check. Check mode reads VERSION."
}

$isCustomRoot = -not [string]::IsNullOrWhiteSpace($RootPath)
if (-not $isCustomRoot) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
} else {
    if (-not (Test-Path -LiteralPath $RootPath -PathType Container)) {
        throw "Repository root does not exist: $RootPath"
    }
    $repoRoot = (Resolve-Path -LiteralPath $RootPath).Path
}

function Replace-VersionField(
    [string]$Content,
    [string]$Pattern,
    [string]$NewVersion,
    [string]$Description
) {
    $regex = [System.Text.RegularExpressions.Regex]::new(
        $Pattern,
        [System.Text.RegularExpressions.RegexOptions]::Multiline
    )
    $matches = $regex.Matches($Content)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one $Description version field; found $($matches.Count). No files were changed."
    }

    $replacement = '${1}' + $NewVersion + '${2}'
    return $regex.Replace($Content, $replacement, 1)
}

$versionPath = Join-Path $repoRoot "VERSION"
if (-not (Test-Path -LiteralPath $versionPath -PathType Leaf)) {
    throw "Canonical version file is missing: VERSION"
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $canonicalVersion = ([System.IO.File]::ReadAllText($versionPath, [System.Text.Encoding]::UTF8)).Trim()
} else {
    $canonicalVersion = $Version.Trim()
    if ($canonicalVersion.StartsWith("v", [System.StringComparison]::OrdinalIgnoreCase)) {
        $canonicalVersion = $canonicalVersion.Substring(1)
    }
}

if ($canonicalVersion -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Version must be valid SemVer (without a leading v). Found: '$canonicalVersion'."
}

# Build and validate the complete write plan before touching any file.
$plan = [System.Collections.Generic.List[object]]::new()
if (-not $Check -and -not [string]::IsNullOrWhiteSpace($Version)) {
    $plan.Add([pscustomobject]@{
        RelativePath = "VERSION"
        Path = $versionPath
        Content = $canonicalVersion + [Environment]::NewLine
    })
}

$targets = @(
    @{
        Path = "desktop/src-tauri/tauri.conf.json"
        Pattern = '(?m)(^  "version"\s*:\s*")[^"]+(")'
        Description = "Tauri configuration"
    },
    @{
        Path = "desktop/src-tauri/Cargo.toml"
        Pattern = '(?ms)(^\[package\]\s*\r?\n.*?^[ \t]*version[ \t]*=[ \t]*")[^"]+(")'
        Description = "clippy-desktop Cargo.toml package"
    },
    @{
        Path = "desktop/src-tauri/Cargo.lock"
        Pattern = '(?m)(^\[\[package\]\]\r?\nname = "clippy-desktop"\r?\nversion = ")[^"]+(")'
        Description = "clippy-desktop Cargo.lock package"
    },
    @{
        Path = "dashboard/package.json"
        Pattern = '(?m)(^  "version"\s*:\s*")[^"]+(")'
        Description = "dashboard package.json"
    },
    @{
        Path = "dashboard/package-lock.json"
        Pattern = '(?m)(^  "version"\s*:\s*")[^"]+(")'
        Description = "dashboard package-lock top-level"
    },
    @{
        Path = "dashboard/package-lock.json"
        Pattern = '(?s)("packages"\s*:\s*\{\s*""\s*:\s*\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"version"\s*:\s*")[^"]+(")'
        Description = "dashboard package-lock root package"
    }
)

foreach ($target in $targets) {
    $path = Join-Path $repoRoot $target.Path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Version metadata file is missing: $($target.Path). No files were changed."
    }

    $original = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    $existing = $plan | Where-Object { $_.Path -eq $path } | Select-Object -First 1
    if ($null -eq $existing) {
        $updated = Replace-VersionField -Content $original -Pattern $target.Pattern -NewVersion $canonicalVersion -Description $target.Description
        $plan.Add([pscustomobject]@{
            RelativePath = $target.Path
            Path = $path
            Content = $updated
        })
    } else {
        # The npm lockfile has two independent Clippy version fields.
        $existing.Content = Replace-VersionField -Content $existing.Content -Pattern $target.Pattern -NewVersion $canonicalVersion -Description $target.Description
    }
}

if ($Check) {
    $outOfSync = @($plan | Where-Object {
        [System.IO.File]::ReadAllText($_.Path, [System.Text.Encoding]::UTF8) -cne $_.Content
    })
    if ($outOfSync.Count -gt 0) {
        $paths = ($outOfSync | ForEach-Object { $_.RelativePath } | Sort-Object -Unique) -join [Environment]::NewLine
        throw "Version metadata is out of sync with VERSION=$canonicalVersion. Run ./desktop/set-version.ps1 to repair: $paths"
    }

    Write-Host "Clippy version $canonicalVersion is synchronized across all manifests." -ForegroundColor Green
    return
}

$encoding = [System.Text.UTF8Encoding]::new($false)
foreach ($entry in $plan) {
    $current = [System.IO.File]::ReadAllText($entry.Path, [System.Text.Encoding]::UTF8)
    if ($current -cne $entry.Content) {
        [System.IO.File]::WriteAllText($entry.Path, $entry.Content, $encoding)
        Write-Host "Updated $($entry.RelativePath)"
    }
}

Write-Host "Clippy version metadata synchronized to $canonicalVersion." -ForegroundColor Green

# Keep the existing read-only validator as the final authority for the complete contract.
if (-not $isCustomRoot) {
    & (Join-Path $PSScriptRoot "validate-version.ps1") -ExpectedVersion $canonicalVersion
}
