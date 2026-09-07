param([ValidateSet('All','SillyTavern','SearXNG','Inference')][string]$Component='All')
. "$PSScriptRoot/services.ps1"
function Checked($Exe, $Arguments, $Directory=$Root) {
    Push-Location $Directory
    try { & $Exe @Arguments; if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" } }
    finally { Pop-Location }
}
& "$Root/stop.ps1"
$stamp=Get-Date -Format yyyyMMdd-HHmmss
$backup="$Root/runtime/backups/$stamp"
New-Item -ItemType Directory -Force $backup | Out-Null
Copy-Item "$Root/config.json" $backup
Copy-Item "$Root/apps/SillyTavern/data/default-user/settings.json" $backup
try {
    if ($Component -in 'All','SillyTavern') {
        $release=Invoke-RestMethod https://api.github.com/repos/SillyTavern/SillyTavern/releases/latest
        if ($release.prerelease -or $release.draft) { throw 'No stable SillyTavern release found.' }
        Checked git @('archive',"--output=$backup/sillytavern-source.zip",'HEAD') "$Root/apps/SillyTavern"
        # Only this project's known managed patch is reset. User data lives outside Git.
        Checked git @('checkout','--','src/endpoints/search.js') "$Root/apps/SillyTavern"
        Checked git @('fetch','--depth','1','origin',"refs/tags/$($release.tag_name)") "$Root/apps/SillyTavern"
        Checked git @('checkout','--detach','FETCH_HEAD') "$Root/apps/SillyTavern"
        Checked npm.cmd @('ci','--no-audit','--no-fund') "$Root/apps/SillyTavern"
        $ext="$Root/apps/SillyTavern/public/scripts/extensions/third-party/Extension-WebSearch"
        Checked git @('archive',"--output=$backup/websearch-source.zip",'HEAD') $ext
        Checked git @('checkout','--','index.js','manifest.json') $ext
        Checked git @('pull','--ff-only') $ext
    }
    if ($Component -in 'All','SearXNG') {
        $sx="$Root/apps/searxng"
        Checked git @('archive',"--output=$backup/searxng-source.zip",'HEAD','searx','requirements.txt','setup.py') $sx
        # SearXNG publishes rolling production commits, not numbered stable releases.
        Checked git @('fetch','--depth','1','origin','master') $sx
        Checked git @('checkout','FETCH_HEAD','--','searx','requirements.txt','setup.py') $sx
        Checked "$Root/runtime/python/Scripts/python.exe" @('-m','pip','install','-r',"$sx/requirements.txt")
    }
    if ($Component -in 'All','Inference') {
        $releases=Invoke-RestMethod 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20'
        $release=$releases | Where-Object { !$_.prerelease -and !$_.draft -and @($_.assets | Where-Object name -Match '^llama-.*-bin-win-cuda-12\.4-x64\.zip$').Count } | Select-Object -First 1
        if (!$release) { throw 'No compatible published CUDA 12.4 Windows build found; existing backend retained.' }
        $target="$Root/apps/llama-$stamp"
        New-Item -ItemType Directory $target | Out-Null
        foreach($asset in @($release.assets | Where-Object name -Match '^(llama-.*-bin|cudart-llama-bin)-win-cuda-12\.4-x64\.zip$')) {
            $zip="$Root/downloads/$($asset.name)"
            Invoke-WebRequest $asset.browser_download_url -OutFile $zip
            if($asset.digest -like 'sha256:*' -and (Get-FileHash $zip).Hash.ToLower() -ne $asset.digest.Substring(7)) { throw 'Backend download checksum mismatch.' }
            Expand-Archive $zip $target -Force
        }
        Checked "$target/llama-server.exe" @('--version')
        # These absolute paths are verified to stay inside this project before moving.
        $old=[IO.Path]::GetFullPath("$Root/apps/llama")
        $dest=[IO.Path]::GetFullPath("$backup/llama")
        if (!$old.StartsWith($Root+[IO.Path]::DirectorySeparatorChar) -or !$dest.StartsWith($Root+[IO.Path]::DirectorySeparatorChar)) { throw 'Backup path outside project.' }
        Move-Item -LiteralPath $old -Destination $dest
        Move-Item -LiteralPath $target -Destination $old
    }
    Checked "$Root/runtime/python/Scripts/python.exe" @("$Root/configure.py")
    Checked "$Root/runtime/python/Scripts/python.exe" @("$Root/patch_extensions.py")
    & "$Root/start.ps1"
    Checked "$Root/runtime/python/Scripts/python.exe" @("$Root/test_stack.py")
    Write-Host "Update verified. Backup: $backup. Model was not replaced."
} catch {
    Write-Error "Update did not pass: $_. Backup: $backup. Review logs before retrying; model and chats are preserved."
}
