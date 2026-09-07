using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class LocalAgent : Form
{
    private readonly string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
    private readonly Label status = new Label();
    private readonly Button retry = new Button();
    private WebView2 web;
    private string localUrl;
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] private static extern bool SetProcessDPIAware();

    [STAThread]
    private static void Main()
    {
        bool created;
        using (var mutex = new Mutex(true, "Local\\UC-LLM-LocalAgent", out created))
        {
            if (!created)
            {
                foreach (var p in Process.GetProcessesByName("Local Agent"))
                    if (p.Id != Process.GetCurrentProcess().Id && p.MainWindowHandle != IntPtr.Zero)
                    { ShowWindow(p.MainWindowHandle, 9); SetForegroundWindow(p.MainWindowHandle); break; }
                return;
            }
            SetProcessDPIAware();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LocalAgent());
        }
    }

    public LocalAgent()
    {
        Text = "N2LLM";
        BackColor = Color.FromArgb(8, 11, 21);
        ForeColor = Color.FromArgb(223, 238, 248);
        Size = new Size(1280, 900);
        MinimumSize = new Size(800, 600);
        StartPosition = FormStartPosition.CenterScreen;
        var icon = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "local-agent.ico");
        if (File.Exists(icon)) Icon = new Icon(icon);
        status.Dock = DockStyle.Fill;
        status.Font = new Font("Segoe UI", 17);
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.ForeColor = Color.FromArgb(83, 238, 221);
        status.Text = "N2LLM\n\nStarter din lokale assistent…";
        Controls.Add(status);
        retry.Text = "Prøv igen";
        retry.Dock = DockStyle.Bottom;
        retry.Height = 48;
        retry.FlatStyle = FlatStyle.Flat;
        retry.Visible = false;
        retry.Click += async delegate { await Initialize(); };
        Controls.Add(retry);
        Shown += async delegate {
            int dark = 1; DwmSetWindowAttribute(Handle, 20, ref dark, 4);
            await Initialize();
        };
    }

    private void Log(string message)
    {
        Directory.CreateDirectory(Path.Combine(root, "logs"));
        File.AppendAllText(Path.Combine(root, "logs", "desktop-app.log"), DateTime.Now.ToString("s") + " " + message + Environment.NewLine);
    }

    private async Task Initialize()
    {
        retry.Visible = false;
        status.Text = "N2LLM\n\nForbinder til lokale tjenester…";
        status.Visible = true;
        try
        {
            var json = new JavaScriptSerializer();
            var config = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(root, "config.json")));
            localUrl = "http://127.0.0.1:" + config["SILLYTAVERN_PORT"] + "/";
            if (!EndpointReady(localUrl))
            {
                await Task.Run(delegate {
                    var pwsh = FindExecutable("pwsh.exe");
                    var executable = pwsh ?? "powershell.exe";
                    var arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(root, "start.ps1") + "\"";
                    var info = new ProcessStartInfo(executable, arguments);
                    info.WorkingDirectory = root; info.UseShellExecute = false; info.CreateNoWindow = true;
                    info.RedirectStandardOutput = true; info.RedirectStandardError = true;
                    using (var process = Process.Start(info))
                    {
                        var output = process.StandardOutput.ReadToEndAsync();
                        var errors = process.StandardError.ReadToEndAsync();
                        process.WaitForExit(); Task.WaitAll(output, errors);
                        Log("Startup exit=" + process.ExitCode + "\n" + output.Result);
                        if (process.ExitCode != 0) throw new Exception("Tjenesterne kunne ikke starte. Se logs-mappen.\n" + errors.Result);
                    }
                });
            }
            else
            {
                Log("Frontend already ready; reusing running services.");
            }
            EnsureFilesService(config);
            status.Text = "N2LLM\n\nÅbner dit workspace…";
            if (web != null) { Controls.Remove(web); web.Dispose(); }
            web = new WebView2();
            web.Dock = DockStyle.Fill;
            web.DefaultBackgroundColor = BackColor;
            Controls.Add(web);
            web.BringToFront();
            var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(root, "runtime", "desktop-profile"));
            await web.EnsureCoreWebView2Async(env);
            web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            web.CoreWebView2.Settings.AreDevToolsEnabled = false;
            web.CoreWebView2.Settings.IsZoomControlEnabled = true;
            web.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = false;
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "document.documentElement.style.background='#080808';" +
                "document.addEventListener('DOMContentLoaded',function(){document.documentElement.dataset.theme='dark';" +
                "document.documentElement.dataset.themeMode='dark';" +
                "document.body.style.background='#080808';document.body.style.color='#f4f1ed';});");
            await web.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                "(function(){function clean(){document.querySelectorAll('.mes').forEach(function(e){" +
                "var t=(e.textContent||'').replace(/\\s+/g,' ').toLowerCase();" +
                "if(t.indexOf(\"if you're connected to an api\")>=0||t.indexOf('set any character as your welcome page assistant')>=0)e.remove();" +
                "});document.querySelectorAll('.welcomeShortcuts,.welcomeButtons').forEach(function(e){e.remove();});}" +
                "clean();setInterval(clean,500);})();");
            web.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                if (e.Uri.StartsWith(localUrl, StringComparison.OrdinalIgnoreCase)) return;
                e.Cancel = true;
                // Only user-initiated source links may leave the local application.
                if (e.IsUserInitiated) OpenExternal(e.Uri);
            };
            web.CoreWebView2.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true;
                if (e.IsUserInitiated) OpenExternal(e.Uri);
            };
            web.CoreWebView2.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                Log("Navigation completed: success=" + e.IsSuccess + ", status=" + e.WebErrorStatus);
                if (!e.IsSuccess) { status.Text = "Kunne ikke åbne assistenten. Prøv igen."; status.BringToFront(); retry.Visible = true; retry.BringToFront(); return; }
                status.Visible = false;
                // Read-only startup diagnostics of our own frontend, without chat content.
                bool frontendReady = false;
                for (int i=0; i<30; i++) {
                    var state = await web.CoreWebView2.ExecuteScriptAsync("JSON.stringify({ready:!!document.querySelector('#send_textarea'),skin:!!document.querySelector('#custom-style'),navigation:!!document.querySelector('#local-agent-navigation'),welcome:!!document.querySelector('#local-agent-welcome'),title:document.title})");
                    if (state.Contains("ready\\\":true") && state.Contains("skin\\\":true") && state.Contains("navigation\\\":true")) { Log("Frontend ready " + state); frontendReady = true; break; }
                    await Task.Delay(1000);
                }
                if (!frontendReady) {
                    Log("Frontend readiness timeout.");
                    status.Text = "N2LLM\n\nFrontend kunne ikke færdiggøre opstarten.";
                    status.Visible = true;
                    retry.Visible = true;
                    retry.BringToFront();
                }
            };
            web.CoreWebView2.Navigate(localUrl);
        }
        catch (Exception e)
        {
            Log("Startup error: " + e);
            status.Text = "Assistenten kunne ikke starte\n\n" + e.Message;
            status.Visible = true; status.BringToFront(); retry.Visible = true; retry.BringToFront();
        }
    }

    private static string FindExecutable(string name)
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var folder in path.Split(Path.PathSeparator))
        {
            if (String.IsNullOrWhiteSpace(folder)) continue;
            var candidate = Path.Combine(folder.Trim(), name);
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }

    private static bool EndpointReady(string address)
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(address);
            request.Timeout = 3000;
            using (var response = (HttpWebResponse)request.GetResponse())
                return (int)response.StatusCode >= 200 && (int)response.StatusCode < 500;
        }
        catch (WebException) { return false; }
    }

    private void EnsureFilesService(Dictionary<string, object> config)
    {
        if (!config.ContainsKey("FILES_PORT")) return;
        var port = Convert.ToInt32(config["FILES_PORT"]);
        var healthUrl = "http://127.0.0.1:" + port + "/health";
        if (EndpointReady(healthUrl)) return;
        var python = Path.Combine(root, "runtime", "python", "Scripts", "python.exe");
        if (!File.Exists(python))
            python = Path.Combine(root, "runtime", "base-python", "python.exe");
        if (!File.Exists(python))
            throw new Exception("File tools runtime mangler: " + python);
        var info = new ProcessStartInfo(python, "\"" + Path.Combine(root, "file_registry_server.py") + "\"");
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        Process.Start(info);
        for (var attempt = 0; attempt < 20; attempt++)
        {
            if (EndpointReady(healthUrl))
            {
                Log("File tools ready on port " + port);
                return;
            }
            Thread.Sleep(500);
        }
        throw new Exception("File tools kunne ikke starte på port " + port + ".");
    }

    private void OpenExternal(string address)
    {
        Uri uri;
        if (Uri.TryCreate(address, UriKind.Absolute, out uri) && (uri.Scheme == "https" || uri.Scheme == "http"))
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }
}
