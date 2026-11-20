BeforeAll {
    . (Join-Path $PSScriptRoot "../runtime-ffmpeg.ps1")
    function Write-Stage([string]$Message) { }
    function Download-File([string]$Url, [string]$Destination) {
        $script:downloadCalls += $Url
        [IO.File]::WriteAllText($Destination, "archive")
    }
    function Assert-Sha256([string]$Path, [string]$Expected) {
        $script:hashCalls++
        if ($script:failFirstHash -and $script:hashCalls -eq 1) {
            throw "Simulated primary archive hash mismatch."
        }
        if ($Expected -ne ("a" * 64)) { throw "Unexpected pinned hash." }
    }
}

Describe "Pinned FFmpeg publisher mirror fallback" {
    BeforeEach {
        $script:downloadCalls = @()
        $script:hashCalls = 0
        $script:failFirstHash = $false
        $script:testRoot = Join-Path ([IO.Path]::GetTempPath()) ("clippy-ffmpeg-test-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $script:testRoot -Force | Out-Null
        $script:archive = Join-Path $script:testRoot "ffmpeg-9.1-essentials_build.zip"
    }

    AfterEach {
        if (Test-Path -LiteralPath $script:testRoot) {
            Remove-Item -LiteralPath $script:testRoot -Recurse -Force
        }
    }

    It "uses the primary endpoint when its archive matches the pinned digest" {
        Get-ClippyFfmpegArchive -PrimaryUrl "https://www.gyan.dev/primary.zip" -FallbackUrl "https://github.com/GyanD/codexffmpeg/releases/download/9.1/ffmpeg-9.1-essentials_build.zip" -ExpectedSha256 ("a" * 64) -ArchivePath $script:archive | Should -Be $script:archive
        $script:downloadCalls | Should -HaveCount 1
        $script:downloadCalls[0] | Should -Be "https://www.gyan.dev/primary.zip"
        $script:hashCalls | Should -Be 1
    }

    It "falls back to the publisher mirror when the primary download fails" {
        function Download-File([string]$Url, [string]$Destination) {
            $script:downloadCalls += $Url
            if ($Url -like "https://www.gyan.dev/*") { throw "Simulated HTTP 503." }
            [IO.File]::WriteAllText($Destination, "archive")
        }
        Get-ClippyFfmpegArchive -PrimaryUrl "https://www.gyan.dev/primary.zip" -FallbackUrl "https://github.com/GyanD/codexffmpeg/releases/download/9.1/ffmpeg-9.1-essentials_build.zip" -ExpectedSha256 ("a" * 64) -ArchivePath $script:archive | Should -Be $script:archive
        $script:downloadCalls | Should -HaveCount 2
        $script:downloadCalls[1] | Should -BeLike "https://github.com/GyanD/codexffmpeg/releases/download/9.1/*"
        Test-Path -LiteralPath $script:archive | Should -BeTrue
    }

    It "falls back when the primary archive does not match the pinned digest" {
        $script:failFirstHash = $true
        Get-ClippyFfmpegArchive -PrimaryUrl "https://www.gyan.dev/primary.zip" -FallbackUrl "https://github.com/GyanD/codexffmpeg/releases/download/9.1/ffmpeg-9.1-essentials_build.zip" -ExpectedSha256 ("a" * 64) -ArchivePath $script:archive | Should -Be $script:archive
        $script:downloadCalls | Should -HaveCount 2
        $script:hashCalls | Should -Be 2
    }

    It "fails closed when the publisher mirror also fails verification" {
        $script:failFirstHash = $true
        function Assert-Sha256([string]$Path, [string]$Expected) { throw "Simulated digest mismatch." }
        { Get-ClippyFfmpegArchive -PrimaryUrl "https://www.gyan.dev/primary.zip" -FallbackUrl "https://github.com/GyanD/codexffmpeg/releases/download/9.1/ffmpeg-9.1-essentials_build.zip" -ExpectedSha256 ("a" * 64) -ArchivePath $script:archive } | Should -Throw "*both configured sources*"
        Test-Path -LiteralPath $script:archive | Should -BeFalse
    }
}
