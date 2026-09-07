$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$package="$root/downloads/webview2"
New-Item -ItemType Directory -Force "$root/downloads" | Out-Null
if (!(Test-Path "$package/lib/net462/Microsoft.Web.WebView2.Core.dll")) {
    $version='1.0.4191.47'
    Invoke-WebRequest "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$version/microsoft.web.webview2.$version.nupkg" -OutFile "$root/downloads/webview2.zip"
    Expand-Archive "$root/downloads/webview2.zip" $package -Force
}
Copy-Item "$package/lib/net462/Microsoft.Web.WebView2.Core.dll","$package/lib/net462/Microsoft.Web.WebView2.WinForms.dll","$package/runtimes/win-x64/native/WebView2Loader.dll" $PSScriptRoot -Force
$logoPath="$root/assets/branding/n2llm-logo.png"
if (!(Test-Path $logoPath)) { throw "N2LLM logo not found: $logoPath" }
# ICO supports PNG payloads directly. Building the directory explicitly avoids
# the malformed single-frame icon produced by Icon.FromHandle on some Windows versions.
Add-Type -AssemblyName System.Drawing
$source=[Drawing.Image]::FromFile($logoPath)
$canvas=[Drawing.Bitmap]::new(256,256)
$graphics=[Drawing.Graphics]::FromImage($canvas)
$graphics.Clear([Drawing.Color]::Transparent)
$graphics.InterpolationMode=[Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.DrawImage($source,0,0,256,256)
$pngStream=New-Object IO.MemoryStream
$canvas.Save($pngStream,[Drawing.Imaging.ImageFormat]::Png)
$png=$pngStream.ToArray()
$graphics.Dispose(); $canvas.Dispose(); $source.Dispose(); $pngStream.Dispose()
$ico=New-Object IO.MemoryStream
$writer=New-Object IO.BinaryWriter($ico)
$writer.Write([UInt16]0); $writer.Write([UInt16]1); $writer.Write([UInt16]1)
$writer.Write([Byte]0); $writer.Write([Byte]0); $writer.Write([Byte]0); $writer.Write([Byte]0)
$writer.Write([UInt16]1); $writer.Write([UInt16]32); $writer.Write([UInt32]$png.Length); $writer.Write([UInt32]22)
$writer.Write($png)
[IO.File]::WriteAllBytes("$PSScriptRoot\local-agent.ico", $ico.ToArray())
$writer.Dispose(); $ico.Dispose()
$compiler="$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe"
& $compiler /nologo /target:winexe /platform:x64 /utf8output "/out:$PSScriptRoot\Local Agent.exe" "/win32icon:$PSScriptRoot\local-agent.ico" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/reference:$PSScriptRoot\Microsoft.Web.WebView2.Core.dll" "/reference:$PSScriptRoot\Microsoft.Web.WebView2.WinForms.dll" "$PSScriptRoot\LocalAgent.cs"
if ($LASTEXITCODE -ne 0) {throw 'Desktop app build failed'}
Write-Host 'N2LLM.exe built successfully.'
