$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'runtime-health.ps1')
$contract = Get-Content (Join-Path $PSScriptRoot 'runtime-contract.json') -Raw | ConvertFrom-Json
if ($contract.schema -ne 1 -or -not $contract.python -or -not $contract.node -or -not $contract.ffmpeg) { throw 'Invalid contract' }
if ($contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract missing' }
$root = Join-Path ([IO.Path]::GetTempPath()) ('clippy-runtime-check-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $root
try {
    $broken = Join-Path $root 'broken.exe'
    [IO.File]::WriteAllText($broken, 'not an executable')
    if (Test-ClippyExecutable $broken '--version') { throw 'Broken executable accepted' }
    if (Test-ClippyExecutable (Join-Path $root 'missing.exe') '--version') { throw 'Missing executable accepted' }
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-ClippyExecutable $shell '-NoProfile -Command "Write-Output healthy"' 'healthy')) { throw 'Healthy executable rejected' }
    if (Test-ClippyExecutable $shell '-NoProfile -Command "Start-Sleep -Seconds 30"' '' 1) { throw 'Timeout accepted' }
    $nativeStage = Join-Path $root 'native.installing'
    $null = New-Item -ItemType Directory $nativeStage
    Copy-Item -LiteralPath $shell -Destination (Join-Path $nativeStage 'powershell.exe')
    Install-ClippyComponent $nativeStage (Join-Path $root 'native') { param($dir) Test-ClippyExecutable (Join-Path $dir 'powershell.exe') '-NoProfile -Command "exit 0"' }
    $current = Join-Path $root 'component'
    $stage = "$current.installing"
    $null = New-Item -ItemType Directory -Path $current,$stage
    [IO.File]::WriteAllText((Join-Path $current 'identity'), 'old')
    [IO.File]::WriteAllText((Join-Path $stage 'identity'), 'new')
    $failed = $false
    try { Install-ClippyComponent $stage $current { param($dir) $dir.EndsWith('.installing') } } catch { $failed = $true }
    if (-not $failed -or [IO.File]::ReadAllText((Join-Path $current 'identity')) -ne 'old') { throw 'Activation did not roll back' }
    Move-Item -LiteralPath $current -Destination "$current.previous"
    Restore-ClippyComponent $current
    if (-not (Test-Path $current)) { throw 'Interrupted activation not restored' }
    $scratch = New-ClippyScratch @($broken, $root) 0
    if (-not $scratch.StartsWith($root) -or -not (Test-Path $scratch)) { throw 'Writable scratch fallback failed' }
    Remove-Item -LiteralPath $scratch -Recurse -Force
    $mutex = Enter-ClippyMutex $root -WaitMilliseconds 0
    try {
        $lockProbe = Join-Path $root 'mutex-probe.ps1'
        [IO.File]::WriteAllText($lockProbe, 'param($helper,$root); . $helper; try { $m=Enter-ClippyMutex $root -WaitMilliseconds 0; $m.ReleaseMutex(); $m.Dispose(); exit 1 } catch { Write-Output excluded }')
        $args = '-NoProfile -File "' + $lockProbe + '" "' + (Join-Path $PSScriptRoot 'runtime-health.ps1') + '" "' + $root + '"'
        if (-not (Test-ClippyExecutable $shell $args 'excluded')) { throw 'Cross-process installation lock failed' }
    } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
    $sdk = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not $sdk.StartsWith([Environment]::GetFolderPath('ProgramFilesX86'))) { throw 'Signing SDK path expansion failed' }
    Write-Host 'Runtime contract, corrupt-executable, timeout, rollback, recovery, writable-scratch and cross-process lock checks passed.'
} finally { Remove-Item -LiteralPath $root -Recurse -Force }
