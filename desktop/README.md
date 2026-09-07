# Local Agent — LUXE desktop

`Local Agent.exe` is a Windows x64 WinForms application using Microsoft's WebView2 runtime. It opens the same local SillyTavern installation in its own window, without browser tabs or an address bar. It uses an isolated browser-data folder in `runtime/desktop-profile`.

The executable starts the stack using `start.ps1`, waits for its health checks, and opens the configured local URL. A second launch brings the existing window to the front. External source links that you click open in your ordinary browser. Closing the window leaves the local services running; `stop.ps1` releases their resources.

Use the **Start Local AI Agent** desktop shortcut, or run `open-app.ps1` from the project folder. The older `start.ps1 -OpenBrowser` argument is retained for compatibility but now opens this app. The preferred spelling is `start.ps1 -OpenApp`.

## Appearance

The installed SillyTavern theme is **LOCAL AGENT — LUXE**. It uses a warm cream background, restrained taupe accents, separate user/assistant bubbles, a wider conversation area and no downloaded fonts. Normal SillyTavern settings remain accessible from the top toolbar. Select another theme in User Settings to revert the appearance.

The original settings hotbar is hidden by default. The compact navigation contains
exactly **CHAT**, **PROFILE** and **SETTINGS**. SETTINGS reveals the existing
SillyTavern settings controls in one grouped panel; it does not remove or reset any
settings.

The theme and navigation are reinstalled by both `desktop/install-skin.py` and
`setup_frontend.py`, so a normal frontend reconfiguration does not remove the LUXE UI.

The stylesheet source is `desktop/neon.css`. To reinstall it after an edit, close the app and reload any old browser tabs after running:

```powershell
.\runtime\python\Scripts\python.exe .\desktop\install-skin.py
.\open-app.ps1
```

Each skin installation backs up the complete previous settings file under `runtime/backups/skin-*`.

## Rebuild

```powershell
.\desktop\build.ps1
```

Close the desktop app before rebuilding its executable. The build uses the Windows .NET Framework compiler and Microsoft.Web.WebView2 **1.0.4191.47**, downloaded from NuGet. The existing Microsoft Edge WebView2 runtime is used. The C# source and icon generator are included. `logs/desktop-app.log` records service startup and frontend readiness without recording conversation content.

Verified: executable builds, native window opens, all services pass startup checks, the frontend and LUXE stylesheet load successfully. The shared frontend was also visually checked in the browser.
