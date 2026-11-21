BeforeAll {
    . (Join-Path $PSScriptRoot "../storage-path.ps1")
}

Describe "Clippy PowerShell storage path normalization" {
    It "preserves normal absolute drive paths and supports Join-Path" {
        $normal = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) "clippy-data"))
        $normalized = ConvertTo-ClippyPowerShellPath -Path $normal
        $normalized | Should -Be $normal
        { Join-Path -Path $normalized -ChildPath "output" } | Should -Not -Throw
    }

    It "converts legacy extended drive paths and supports Join-Path" {
        $normal = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) "clippy-data"))
        $extended = '\\?\' + $normal
        $normalized = ConvertTo-ClippyPowerShellPath -Path $extended
        $normalized | Should -Be $normal
        { Join-Path -Path $normalized -ChildPath "output" } | Should -Not -Throw
    }

    It "converts extended UNC paths without changing the server or share" {
        $normalized = ConvertTo-ClippyPowerShellPath -Path '\\?\UNC\server\share\clippy-data'
        $normalized | Should -Be '\\server\share\clippy-data'
    }

    It "rejects unsupported extended device paths instead of mangling them" {
        { ConvertTo-ClippyPowerShellPath -Path '\\?\Volume{00000000-0000-0000-0000-000000000000}\clippy-data' } |
            Should -Throw "*Unsupported extended Clippy data path*"
    }

    It "does not strip the extended prefix from paths beyond the safe PowerShell limit" {
        $longPath = '\\?\C:\' + ('x' * 260)
        { ConvertTo-ClippyPowerShellPath -Path $longPath } |
            Should -Throw "*requires extended-length Windows path support*"
    }

    It "does not strip the extended prefix from reserved device-name paths" {
        { ConvertTo-ClippyPowerShellPath -Path '\\?\C:\CON\clippy-data' } |
            Should -Throw "*reserved Windows device name*"
    }
}
