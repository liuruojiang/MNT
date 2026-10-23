param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$Commit
)

# Run in the user's terminal: this session cannot write the repository .git.
# No working files are checked out, restored, or overwritten.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$baseline = '4f3e18a704b42df23cf5c8f8182cf60901563fba'
Set-Location -LiteralPath $repoRoot

function Invoke-GitChecked {
    param([string[]]$Arguments)
    $result = & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git failed: $($Arguments -join ' ')" }
    return $result
}

$branch = Invoke-GitChecked -Arguments @('branch', '--show-current')
$head = Invoke-GitChecked -Arguments @('rev-parse', 'HEAD')
$origin = Invoke-GitChecked -Arguments @('remote', 'get-url', 'origin')
if ($branch -ne 'main' -or $head -notin @($baseline, $Commit)) {
    throw 'Local branch has advanced or changed. Stop for review; no reset was performed.'
}
if ($origin -ne 'https://github.com/liuruojiang/MNT.git') {
    throw 'Unexpected origin; stop for review.'
}
Invoke-GitChecked -Arguments @('fetch', 'origin', 'main')
$remoteHead = Invoke-GitChecked -Arguments @('rev-parse', 'refs/remotes/origin/main')
if ($remoteHead -ne $Commit) {
    throw 'Remote main differs from the reviewed commit. Stop for review.'
}
$parent = Invoke-GitChecked -Arguments @('rev-parse', "$Commit^1")
if ($parent -ne $baseline) { throw 'Unexpected commit parent.' }

# Verify every published changed file against its Git blob before updating HEAD.
$changed = @(Invoke-GitChecked -Arguments @('-c', 'core.quotePath=false', 'diff-tree', '--no-commit-id', '--name-status', '-r', $baseline, $Commit))
foreach ($line in $changed) {
    $parts = $line -split "`t", 2
    if ($parts.Count -ne 2 -or $parts[0] -notin @('A', 'M')) {
        throw "Unexpected change type: $line"
    }
    $relative = $parts[1]
    $full = [IO.Path]::GetFullPath((Join-Path $repoRoot $relative))
    if (-not $full.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside workspace: $relative"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "Missing file: $relative" }
    $expected = Invoke-GitChecked -Arguments @('rev-parse', "${Commit}:$relative")
    $actual = Invoke-GitChecked -Arguments @('hash-object', "--path=$relative", '--', $full)
    if ($actual -ne $expected) { throw "Local file changed since publication: $relative" }
}

# Only disposable directories created by the 2026-10-23 V8 audit are included.
$temporaryPaths = @(
    'outputs/v80_repairs_20261023',
    'outputs/audit_v80_20261023_display_tmp',
    'outputs/v80_audit_20261023_tmp_bfd8bbd5373547b8815e31840e96d85b',
    'outputs/v80_cleanup_verify_961dc9a8068140e99a2a5aacbe663fb3',
    'outputs/v80_cleanup_verify_path.txt',
    'outputs/v80_publish_bundle_20261023.json'
)
foreach ($relative in $temporaryPaths) {
    $target = Join-Path $repoRoot $relative
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolved.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup path outside workspace: $resolved"
    }
    $item = Get-Item -LiteralPath $resolved -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse cleanup target rejected.' }
    if ($item.PSIsContainer) {
        $links = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($links.Count) { throw 'Reparse cleanup child rejected.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    } else {
        Remove-Item -LiteralPath $resolved -Force
    }
}

# Mixed reset changes only HEAD/index; the verified working files stay intact.
Invoke-GitChecked -Arguments @('reset', '--mixed', $Commit)
$status = @(Invoke-GitChecked -Arguments @('status', '--porcelain'))
if ($status.Count) {
    $status | Write-Output
    throw 'Other local changes remain; they were preserved.'
}
Write-Output "Local main and origin/main are synchronized at $Commit; working tree is clean."
