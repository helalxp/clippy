# Download the pinned FFmpeg build from Gyan's primary endpoint, then fall back
# to the publisher's GitHub Releases mirror. Both sources must provide the
# exact same pinned archive; the SHA-256 is stored in runtime-contract.json.
function Get-ClippyFfmpegArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PrimaryUrl,
        [Parameter(Mandatory = $true)][string]$FallbackUrl,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$ArchivePath
    )

    if ($ExpectedSha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw "FFmpeg runtime contract contains an invalid SHA-256 digest."
    }

    $PartialPath = "$ArchivePath.partial"
    try {
        Write-Stage "Downloading pinned FFmpeg archive from the primary publisher endpoint."
        Download-File $PrimaryUrl $ArchivePath
        Assert-Sha256 $ArchivePath $ExpectedSha256
        Write-Stage "FFmpeg primary download passed SHA-256 verification."
        return $ArchivePath
    } catch {
        $PrimaryFailure = $_.Exception.Message
        Write-Stage "FFmpeg primary endpoint failed verification or download; switching to the publisher's GitHub Releases mirror. $PrimaryFailure"
        Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PartialPath -Force -ErrorAction SilentlyContinue
    }

    try {
        Write-Stage "Downloading pinned FFmpeg archive from the publisher's GitHub Releases mirror."
        Download-File $FallbackUrl $ArchivePath
        Assert-Sha256 $ArchivePath $ExpectedSha256
        Write-Stage "FFmpeg publisher mirror download passed SHA-256 verification."
        return $ArchivePath
    } catch {
        $FallbackFailure = $_.Exception.Message
        Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PartialPath -Force -ErrorAction SilentlyContinue
        throw "FFmpeg download failed from both configured sources. Primary: $PrimaryUrl ($PrimaryFailure). Publisher mirror: $FallbackUrl ($FallbackFailure)"
    }
}
