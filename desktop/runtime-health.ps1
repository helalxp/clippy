# Shared by setup and regression checks; no installation side effects on import.
function Test-ClippyExecutable([string]$Path, [string]$Arguments, [string]$Expected = "", [int]$TimeoutSeconds = 30) {
    $process = $null
    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Path
        $info.Arguments = $Arguments
        $info.WorkingDirectory = (Get-Location).ProviderPath
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        if (-not $process.Start()) { return $false }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F *> $null
            return $false
        }
        if ($process.ExitCode -ne 0) { return $false }
        if ($Expected) { return ($stdout.Result.Trim() -eq $Expected -or $stderr.Result.Trim() -eq $Expected) }
        return $true
    } catch { return $false } finally { if ($process) { $process.Dispose() } }
}

# Windows scanners can retain a new executable briefly after its probe exits.
# Retry only transient sharing/access errors; never delete the active runtime.
function Move-ClippyDirectory([string]$Source, [string]$Destination) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { [IO.Directory]::Move($Source, $Destination); return } catch {
            $cause = $_.Exception
            while ($cause.InnerException) { $cause = $cause.InnerException }
            $code = $cause.HResult -band 0xffff
            if ($code -notin @(5,32,33) -or $attempt -eq 29) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Restore-ClippyComponent([string]$Destination) {
    $backup = "$Destination.previous"
    if (-not (Test-Path -LiteralPath $Destination) -and (Test-Path -LiteralPath $backup)) {
        Move-ClippyDirectory $backup $Destination
    }
}

function Install-ClippyComponent([string]$Stage, [string]$Destination, [scriptblock]$Validate) {
    Restore-ClippyComponent $Destination
    if (-not (& $Validate $Stage)) { throw "Staged runtime failed validation: $Stage" }
    $backup = "$Destination.previous"
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    $hadCurrent = Test-Path -LiteralPath $Destination
    if ($hadCurrent) { Move-ClippyDirectory $Destination $backup }
    try {
        Move-ClippyDirectory $Stage $Destination
        if (-not (& $Validate $Destination)) { throw "Activated runtime failed validation: $Destination" }
    } catch {
        if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
        if ($hadCurrent) { Move-ClippyDirectory $backup $Destination }
        throw
    }
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
}

function New-ClippyScratch([string[]]$Candidates, [long]$MinimumFreeBytes = 12GB, [string]$RuntimeRoot = '') {
    foreach ($candidate in $Candidates) {
        $scratch = $null
        try {
            $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($candidate))
            $required = $MinimumFreeBytes
            if ($RuntimeRoot -and $drive.Name -eq [IO.Path]::GetPathRoot($RuntimeRoot)) { $required += 10GB }
            if (-not $drive.IsReady -or $drive.AvailableFreeSpace -lt $required) { continue }
            $scratch = Join-Path $candidate ("ClippySetupTemp-" + [guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Path $scratch -ErrorAction Stop
            $probe = Join-Path $scratch '.write-test'
            [IO.File]::WriteAllText($probe, 'ok')
            Remove-Item -LiteralPath $probe -Force
            return $scratch
        } catch {
            if ($scratch -and (Test-Path -LiteralPath $scratch)) { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }
    throw 'No writable temporary location has enough free space for runtime setup.'
}

function Enter-ClippyMutex([string]$Root, [string]$Purpose = 'Install', [int]$WaitMilliseconds = 300000) {
    $normalized = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized)))).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, "Local\Clippy.$Purpose.$hash")
    try {
        try { $acquired = $mutex.WaitOne($WaitMilliseconds) } catch [Threading.AbandonedMutexException] { $acquired = $true }
        if (-not $acquired) { throw 'Another Clippy installation is still running. Close it and try again.' }
        return $mutex
    } catch { $mutex.Dispose(); throw }
}
