BeforeAll {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    . (Join-Path $PSScriptRoot "../runtime-archive.ps1")
}

Describe "Runtime release archive manifest contract" {
    It "calculates a standard SHA-256 digest with the platform crypto API" {
        $testFile = Join-Path ([IO.Path]::GetTempPath()) ("clippy-sha256-" + [guid]::NewGuid().ToString("N"))
        $bytes = [Text.Encoding]::UTF8.GetBytes("Clippy runtime archive hash contract")
        [IO.File]::WriteAllBytes($testFile, $bytes)
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $expected = ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
        } finally {
            $algorithm.Dispose()
        }
        try {
            (Get-ClippyFileSha256 $testFile) | Should -Be $expected
        } finally {
            Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
        }
    }

    BeforeEach {
        $testRoot = Join-Path ([IO.Path]::GetTempPath()) ("clippy-runtime-test-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
        $source = Join-Path $testRoot "clippy-python-cuda.zip"
        $script:sourceUncompressedBytes = 2MB + 12345
        $bytes = New-Object byte[] $script:sourceUncompressedBytes
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $zip = [System.IO.Compression.ZipFile]::Open($source, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            $entry = $zip.CreateEntry("runtime.bin", [System.IO.Compression.CompressionLevel]::NoCompression)
            $entryStream = $entry.Open()
            try { $entryStream.Write($bytes, 0, $bytes.Length) } finally { $entryStream.Dispose() }
        } finally {
            $zip.Dispose()
        }
    }

    AfterEach {
        if (Test-Path -LiteralPath $testRoot) {
            Remove-Item -LiteralPath $testRoot -Recurse -Force
        }
    }

    It "splits an archive into safe parts and reconstructs it byte-for-byte" {
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $manifest.partCount | Should -Be 3
        Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion "0.2.2" -ExpectedVariant cuda -MaximumPartBytes 1MB | Should -BeTrue
        $reconstructed = Join-Path $testRoot "roundtrip.zip"
        Join-ClippyRuntimeArchiveParts -Manifest $manifest -PartsDirectory $testRoot -Destination $reconstructed | Should -Be $reconstructed
        (Get-ClippyFileSha256 $reconstructed) | Should -Be $manifest.archive.sha256
        (Get-Item $reconstructed).Length | Should -Be $manifest.archive.size
    }

    It "keeps a small CPU runtime as one canonical ZIP asset" {
        $cpuArchive = Join-Path $testRoot "clippy-python-cpu.zip"
        Copy-Item -LiteralPath $source -Destination $cpuArchive
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $cpuArchive -OutputDirectory $testRoot -Variant cpu -ApplicationVersion "0.2.2" -MaximumPartBytes 10MB
        $manifest.partCount | Should -Be 1
        $manifest.parts[0].name | Should -Be "clippy-python-cpu.zip"
        $manifest.archive.uncompressedSize | Should -Be $script:sourceUncompressedBytes
        (Test-Path -LiteralPath $cpuArchive) | Should -BeTrue
    }

    It "records the true uncompressed runtime size for disk-space preflight" {
        # Multipart manifest creation intentionally deletes the original ZIP
        # after verified parts have been written. Measure the source before
        # creation, then assert the signed-off manifest retained that value.
        $actualExpandedSize = Get-ClippyZipUncompressedSize -Path $source
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $actualExpandedSize | Should -Be $script:sourceUncompressedBytes
        $manifest.archive.uncompressedSize | Should -Be $actualExpandedSize
        (Test-Path -LiteralPath $source) | Should -BeFalse
    }

    It "rejects missing or unsafe uncompressed-size metadata" {
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $manifest.archive.uncompressedSize = 0
        { Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion "0.2.2" -ExpectedVariant cuda } | Should -Throw
    }

    It "rejects a corrupt ZIP before publishing its expanded-size metadata" {
        $invalidArchive = Join-Path $testRoot "invalid.zip"
        [IO.File]::WriteAllBytes($invalidArchive, [Text.Encoding]::UTF8.GetBytes("not a zip"))
        { Get-ClippyZipUncompressedSize -Path $invalidArchive } | Should -Throw
    }

    It "rejects a manifest for a different application version or runtime variant" {
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        { Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion "0.2.3" -ExpectedVariant cuda -MaximumPartBytes 1MB } | Should -Throw
        { Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion "0.2.2" -ExpectedVariant cpu -MaximumPartBytes 1MB } | Should -Throw
    }

    It "rejects corrupted parts before archive extraction can occur" {
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $partPath = Join-Path $testRoot $manifest.parts[0].name
        [IO.File]::WriteAllBytes($partPath, (New-Object byte[] 16))
        { Join-ClippyRuntimeArchiveParts -Manifest $manifest -PartsDirectory $testRoot -Destination (Join-Path $testRoot "bad.zip") } | Should -Throw
    }

    It "rejects unsafe path traversal in part names" {
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $source -OutputDirectory $testRoot -Variant cuda -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $manifest.parts[0].name = "../payload.zip"
        { Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion "0.2.2" -ExpectedVariant cuda -MaximumPartBytes 1MB } | Should -Throw
    }
}
