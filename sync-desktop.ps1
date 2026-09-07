param(
    [ValidateSet('Status','FromDesktop','ToDesktop')]
    [string]$Direction='Status',
    [string]$DesktopPath='C:\Users\Never\Desktop\UC-LLM'
)

$ErrorActionPreference='Stop'
$RepositoryPath=$PSScriptRoot
$sourceFiles=@(
    'sync-desktop.ps1',
    'config.json',
    'file_registry.py',
    'file_registry_server.py',
    'local_tools.py',
    'benchmark-context.py',
    'configure.py',
    'open-app.ps1',
    'patch_extensions.py',
    'restart.ps1',
    'searx_server.py',
    'services.ps1',
    'setup_frontend.py',
    'start.ps1',
    'status.ps1',
    'stop.ps1',
    'system-prompt.txt',
    'test-lifecycle.ps1',
    'test_stack.py',
    'update.ps1',
    'desktop\build.ps1',
    'desktop\install-skin.py',
    'desktop\LocalAgent.cs',
    'desktop\neon.css',
    'desktop\local-agent-ui.js',
    'desktop\local-agent-ui.css',
    'assets\branding\n2llm-logo.png',
    'desktop\assets\fonts\SpaceGrotesk.ttf',
    'desktop\assets\fonts\BodoniModa.ttf',
    'desktop\assets\fonts\IBMPlexMono.ttf',
    'desktop\README.md',
    'desktop\WebView2-LICENSE.txt',
    'desktop\WebView2-NOTICE.txt'
)

function Get-ComparableHash($Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $text=[IO.File]::ReadAllText($Path)
    $text=$text.Replace("`r`n","`n").Replace("`r","`n")
    $bytes=[Text.Encoding]::UTF8.GetBytes($text)
    $sha=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','') }
    finally { $sha.Dispose() }
}

if (!(Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw "Desktop installation not found: $DesktopPath"
}

$different=@()
$missing=@()
foreach($relative in $sourceFiles) {
    $repoFile=Join-Path $RepositoryPath $relative
    $desktopFile=Join-Path $DesktopPath $relative
    $repoHash=Get-ComparableHash $repoFile
    $desktopHash=Get-ComparableHash $desktopFile
    if (!$repoHash -or !$desktopHash) {
        $missing += $relative
    } elseif ($repoHash -ne $desktopHash) {
        $different += $relative
    }
}

if ($Direction -eq 'Status') {
    if (!$different.Count -and !$missing.Count) {
        Write-Host 'Desktop installation and repository source are in sync.'
        exit 0
    }
    if ($different.Count) {
        Write-Host 'Different files:'
        $different | ForEach-Object { Write-Host "  $_" }
    }
    if ($missing.Count) {
        Write-Host 'Missing files:'
        $missing | ForEach-Object { Write-Host "  $_" }
    }
    exit 1
}

if ($different.Count -and $Direction -eq 'FromDesktop') {
    $destinationRoot=$RepositoryPath
} elseif ($different.Count -and $Direction -eq 'ToDesktop') {
    $destinationRoot=$DesktopPath
} else {
    $destinationRoot=if($Direction -eq 'FromDesktop'){$RepositoryPath}else{$DesktopPath}
}

if ($different.Count -and $Direction -eq 'FromDesktop') {
    foreach($relative in $sourceFiles) {
        $repoFile=Join-Path $RepositoryPath $relative
        $desktopFile=Join-Path $DesktopPath $relative
        if ((Get-ComparableHash $repoFile) -and (Get-ComparableHash $desktopFile) -and
            (Get-ComparableHash $repoFile) -ne (Get-ComparableHash $desktopFile)) {
            Copy-Item -LiteralPath $desktopFile -Destination $repoFile -Force
        }
    }
} elseif ($different.Count -and $Direction -eq 'ToDesktop') {
    foreach($relative in $sourceFiles) {
        $repoFile=Join-Path $RepositoryPath $relative
        $desktopFile=Join-Path $DesktopPath $relative
        if ((Get-ComparableHash $repoFile) -and (Get-ComparableHash $desktopFile) -and
            (Get-ComparableHash $repoFile) -ne (Get-ComparableHash $desktopFile)) {
            Copy-Item -LiteralPath $repoFile -Destination $desktopFile -Force
        }
    }
}

foreach($relative in $sourceFiles) {
    $source=if($Direction -eq 'FromDesktop'){Join-Path $DesktopPath $relative}else{Join-Path $RepositoryPath $relative}
    $destination=if($Direction -eq 'FromDesktop'){Join-Path $RepositoryPath $relative}else{Join-Path $DesktopPath $relative}
    if (!(Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $parent=Split-Path -Parent $destination
    New-Item -ItemType Directory -Force $parent | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

Write-Host "Sync complete: $Direction"
