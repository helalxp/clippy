# Shared runtime archive manifest and multipart helpers.
# Compatible with Windows PowerShell 5.1 and PowerShell 7.
$script:ClippyRuntimeMaxPartBytes = [long](1.75 * 1GB)

function Get-ClippyFileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-ClippyRuntimePartName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or
        $Name -notmatch '^clippy-python-(cpu|cuda)(?:\.zip|\.part\d{3,})$' -or
        [IO.Path]::GetFileName($Name) -ne $Name) {
        throw "Runtime manifest contains an unsafe or invalid part filename: '$Name'."
    }
}

function New-ClippyRuntimeArchiveManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][ValidateSet("cpu", "cuda")][string]$Variant,
        [Parameter(Mandatory = $true)][string]$ApplicationVersion,
        [long]$MaximumPartBytes = $script:ClippyRuntimeMaxPartBytes
    )

    if ($MaximumPartBytes -lt 1MB -or $MaximumPartBytes -ge 2GB) {
        throw "Maximum runtime part size must be at least 1 MiB and strictly below 2 GiB."
    }
    if ($ApplicationVersion -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
        throw "Invalid application version for runtime manifest: $ApplicationVersion"
    }
    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
        throw "Runtime archive does not exist: $ArchivePath"
    }

    $archiveName = "clippy-python-$Variant.zip"
    $archiveSize = (Get-Item -LiteralPath $ArchivePath).Length
    $archiveHash = Get-ClippyFileSha256 $ArchivePath
    $partFiles = New-Object System.Collections.Generic.List[object]

    if ($archiveSize -le $MaximumPartBytes) {
        $partFiles.Add([pscustomobject]@{
            name = $archiveName
            size = [long]$archiveSize
            sha256 = $archiveHash
        })
    } else {
        $source = [IO.File]::Open($ArchivePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            $buffer = New-Object byte[] (8 * 1024 * 1024)
            $partIndex = 0
            while ($source.Position -lt $source.Length) {
                $partIndex++
                $partName = "clippy-python-$Variant.part{0:D3}" -f $partIndex
                $partPath = Join-Path $OutputDirectory $partName
                $target = [IO.File]::Open($partPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
                $partBytes = 0L
                $partHasher = [Security.Cryptography.SHA256]::Create()
                try {
                    while ($partBytes -lt $MaximumPartBytes) {
                        $remaining = $MaximumPartBytes - $partBytes
                        $readLimit = [int][Math]::Min([long]$buffer.Length, $remaining)
                        $read = $source.Read($buffer, 0, $readLimit)
                        if ($read -le 0) { break }
                        $target.Write($buffer, 0, $read)
                        [void]$partHasher.TransformBlock($buffer, 0, $read, $buffer, 0)
                        $partBytes += $read
                    }
                    [void]$partHasher.TransformFinalBlock((New-Object byte[] 0), 0, 0)
                } finally {
                    $target.Dispose()
                }
                $partHash = ([BitConverter]::ToString($partHasher.Hash)).Replace("-", "").ToLowerInvariant()
                $partHasher.Dispose()
                if ($partBytes -le 0 -or $partBytes -ge 2GB) {
                    throw "Generated runtime part has an invalid size: $partName ($partBytes bytes)."
                }
                $partFiles.Add([pscustomobject]@{ name = $partName; size = [long]$partBytes; sha256 = $partHash })
            }
        } finally {
            $source.Dispose()
        }
    }

    $manifest = [ordered]@{
        schema = 1
        applicationVersion = $ApplicationVersion
        runtimeVariant = $Variant
        archive = [ordered]@{
            name = $archiveName
            size = [long]$archiveSize
            sha256 = $archiveHash
        }
        partCount = $partFiles.Count
        parts = @($partFiles.ToArray())
    }
    $manifestPath = Join-Path $OutputDirectory "clippy-python-$Variant.manifest.json"
    $json = $manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($manifestPath, $json, [Text.UTF8Encoding]::new($false))

    # Reconstruct and verify the exact archive before CI is allowed to upload it.
    $reconstructed = Join-Path $OutputDirectory "clippy-python-$Variant.reconstructed.zip"
    Join-ClippyRuntimeArchiveParts -Manifest $manifest -PartsDirectory $OutputDirectory -Destination $reconstructed | Out-Null
    if ((Get-Item -LiteralPath $reconstructed).Length -ne $archiveSize -or
        (Get-ClippyFileSha256 $reconstructed) -ne $archiveHash) {
        throw "Reconstructed $Variant runtime archive does not match the original archive."
    }
    Remove-Item -LiteralPath $reconstructed -Force

    if ($partFiles.Count -gt 1) {
        Remove-Item -LiteralPath $ArchivePath -Force
        Remove-Item -LiteralPath "$ArchivePath.sha256" -Force -ErrorAction SilentlyContinue
    }

    $checksumLines = @()
    foreach ($part in $partFiles) {
        $partPath = Join-Path $OutputDirectory $part.name
        $checksumLines += "$($part.sha256)  $($part.name)"
    }
    $checksumLines += "$archiveHash  $archiveName (reconstructed archive)"
    [IO.File]::WriteAllLines((Join-Path $OutputDirectory "clippy-python-$Variant.parts.sha256"), $checksumLines, [Text.Encoding]::ASCII)
    return $manifest
}

function Assert-ClippyRuntimeArchiveManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$ExpectedApplicationVersion,
        [Parameter(Mandatory = $true)][ValidateSet("cpu", "cuda")][string]$ExpectedVariant,
        [long]$MaximumPartBytes = $script:ClippyRuntimeMaxPartBytes
    )

    if ($Manifest.schema -ne 1) { throw "Unsupported runtime manifest schema. Expected 1." }
    if ([string]$Manifest.applicationVersion -ne $ExpectedApplicationVersion) {
        throw "Runtime manifest version mismatch. Installer expects $ExpectedApplicationVersion; manifest declares '$($Manifest.applicationVersion)'."
    }
    if ([string]$Manifest.runtimeVariant -ne $ExpectedVariant) {
        throw "Runtime manifest variant mismatch. Expected $ExpectedVariant; manifest declares '$($Manifest.runtimeVariant)'."
    }
    if ($Manifest.archive.name -ne "clippy-python-$ExpectedVariant.zip" -or
        [long]$Manifest.archive.size -le 0 -or
        [string]$Manifest.archive.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw "Runtime manifest archive metadata is invalid."
    }
    if ($null -eq $Manifest.parts -or @($Manifest.parts).Count -lt 1 -or
        [int]$Manifest.partCount -ne @($Manifest.parts).Count) {
        throw "Runtime manifest part count is invalid."
    }
    $totalBytes = 0L
    $seen = @{}
    foreach ($part in @($Manifest.parts)) {
        Assert-ClippyRuntimePartName ([string]$part.name)
        if (-not ([string]$part.name).StartsWith("clippy-python-$ExpectedVariant", [StringComparison]::Ordinal)) {
            throw "Runtime part belongs to a different variant: $($part.name)"
        }
        if ($seen.ContainsKey([string]$part.name)) { throw "Runtime manifest contains duplicate part '$($part.name)'." }
        $seen[[string]$part.name] = $true
        $size = [long]$part.size
        if ($size -le 0 -or $size -gt $MaximumPartBytes -or $size -ge 2GB) {
            throw "Runtime part size is invalid or exceeds the safe release limit: $($part.name) ($size bytes)."
        }
        if ([string]$part.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
            throw "Runtime part SHA-256 is invalid: $($part.name)"
        }
        $totalBytes += $size
    }
    if ($totalBytes -ne [long]$Manifest.archive.size) {
        throw "Runtime manifest part sizes total $totalBytes bytes, but archive size is $($Manifest.archive.size) bytes."
    }
    if (@($Manifest.parts).Count -eq 1 -and $Manifest.parts[0].name -ne $Manifest.archive.name) {
        throw "A single-part runtime must use the canonical archive asset name."
    }
    if (@($Manifest.parts).Count -gt 1 -and @($Manifest.parts | Where-Object { $_.name -eq $Manifest.archive.name }).Count -gt 0) {
        throw "A multipart runtime cannot also name the original archive as a downloadable part."
    }
    return $true
}

function Join-ClippyRuntimeArchiveParts {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$PartsDirectory,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $destinationPartial = "$Destination.partial"
    if (Test-Path -LiteralPath $destinationPartial) { Remove-Item -LiteralPath $destinationPartial -Force }
    $output = [IO.File]::Open($destinationPartial, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $buffer = New-Object byte[] (8 * 1024 * 1024)
    $total = 0L
    try {
        foreach ($part in @($Manifest.parts)) {
            Assert-ClippyRuntimePartName ([string]$part.name)
            $partPath = Join-Path $PartsDirectory ([string]$part.name)
            if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
                throw "Runtime archive part is missing: $($part.name)"
            }
            $info = Get-Item -LiteralPath $partPath
            if ($info.Length -ne [long]$part.size) {
                throw "Runtime archive part has the wrong size: $($part.name). Expected $($part.size), got $($info.Length)."
            }
            $actualHash = Get-ClippyFileSha256 $partPath
            if ($actualHash -ne ([string]$part.sha256).ToLowerInvariant()) {
                throw "Runtime archive part SHA-256 verification failed: $($part.name)"
            }
            $input = [IO.File]::Open($partPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            try {
                while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $read)
                    $total += $read
                }
            } finally {
                $input.Dispose()
            }
        }
        $output.Flush()
    } catch {
        $output.Dispose()
        Remove-Item -LiteralPath $destinationPartial -Force -ErrorAction SilentlyContinue
        throw
    }
    $output.Dispose()
    if ($total -ne [long]$Manifest.archive.size) {
        Remove-Item -LiteralPath $destinationPartial -Force -ErrorAction SilentlyContinue
        throw "Reconstructed runtime archive size mismatch. Expected $($Manifest.archive.size), got $total."
    }
    $archiveHash = Get-ClippyFileSha256 $destinationPartial
    if ($archiveHash -ne ([string]$Manifest.archive.sha256).ToLowerInvariant()) {
        Remove-Item -LiteralPath $destinationPartial -Force -ErrorAction SilentlyContinue
        throw "Reconstructed runtime archive SHA-256 verification failed."
    }
    Move-Item -LiteralPath $destinationPartial -Destination $Destination -Force
    return $Destination
}
