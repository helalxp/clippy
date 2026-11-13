BeforeAll {
    . (Join-Path $PSScriptRoot "../runtime-archive.ps1")
}

Describe "Runtime release archive manifest contract" {
    BeforeEach {
        $testRoot = Join-Path ([IO.Path]::GetTempPath()) ("clippy-runtime-test-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
        $source = Join-Path $testRoot "clippy-python-cuda.zip"
        $bytes = New-Object byte[] (2MB + 12345)
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [IO.File]::WriteAllBytes($source, $bytes)
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
        [IO.File]::WriteAllBytes($cpuArchive, (New-Object byte[] 4096))
        $manifest = New-ClippyRuntimeArchiveManifest -ArchivePath $cpuArchive -OutputDirectory $testRoot -Variant cpu -ApplicationVersion "0.2.2" -MaximumPartBytes 1MB
        $manifest.partCount | Should -Be 1
        $manifest.parts[0].name | Should -Be "clippy-python-cpu.zip"
        (Test-Path -LiteralPath $cpuArchive) | Should -BeTrue
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
