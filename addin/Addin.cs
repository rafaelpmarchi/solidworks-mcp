// Add-in do SolidWorks que hospeda o chat Claude num taskpane (WebView2).
// O backend (python -m swmcp.chat) é iniciado automaticamente se não estiver no ar.

using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

namespace SwClaudeAddin
{
    [ComVisible(true)]
    [Guid(ADDIN_GUID)]
    public class Addin : ISwAddin
    {
        public const string ADDIN_GUID = "7A5ED539-6B43-4A0E-9F2B-1C34D2A0C0DE";
        private const string TITLE = "Claude";
        private const string DESCRIPTION = "Chat Claude para leitura e revisão de desenhos (Gromar)";
        private const string BACKEND_URL = "http://127.0.0.1:8765/";

        private ISldWorks? _app;
        private ITaskpaneView? _taskpane;
        private ChatControl? _control;
        private Process? _backend;

        public bool ConnectToSW(object thisSw, int cookie)
        {
            _app = (ISldWorks)thisSw;
            _app.SetAddinCallbackInfo2(0, this, cookie);

            EnsureBackendRunning();

            var iconPath = Path.Combine(
                Path.GetDirectoryName(typeof(Addin).Assembly.Location) ?? "",
                "claude-icon.bmp");
            _taskpane = (ITaskpaneView)_app.CreateTaskpaneView2(
                File.Exists(iconPath) ? iconPath : "", TITLE);
            _control = new ChatControl(BACKEND_URL);
            _taskpane.DisplayWindowFromHandlex64(_control.Handle.ToInt64());
            return true;
        }

        public bool DisconnectFromSW()
        {
            try { _control?.Dispose(); } catch { }
            try { _taskpane?.DeleteView(); } catch { }
            if (_taskpane != null) Marshal.FinalReleaseComObject(_taskpane);
            _taskpane = null;
            _control = null;
            // só derruba o backend se fomos nós que o iniciamos
            try { if (_backend != null && !_backend.HasExited) _backend.Kill(); } catch { }
            _backend = null;
            _app = null;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            return true;
        }

        private void EnsureBackendRunning()
        {
            if (BackendAlive()) return;
            var cmd = System.Environment.GetEnvironmentVariable("SWMCP_CHAT_CMD");
            string file;
            string args;
            if (!string.IsNullOrWhiteSpace(cmd))
            {
                file = cmd!;
                args = "";
            }
            else
            {
                file = @"C:\Users\peron\Documents\Github\solidworks\.venv\Scripts\python.exe";
                args = "-m swmcp.chat";
            }
            try
            {
                _backend = Process.Start(new ProcessStartInfo
                {
                    FileName = file,
                    Arguments = args,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WorkingDirectory = Path.GetDirectoryName(file) ?? ".",
                });
                // espera o /health responder (até ~10s)
                for (int i = 0; i < 20 && !BackendAlive(); i++)
                    System.Threading.Thread.Sleep(500);
            }
            catch
            {
                // sem backend o WebView mostra a página de erro com instruções
            }
        }

        private static bool BackendAlive()
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(BACKEND_URL + "health");
                req.Timeout = 1000;
                using var resp = (HttpWebResponse)req.GetResponse();
                return resp.StatusCode == HttpStatusCode.OK;
            }
            catch { return false; }
        }

        // ------------------------------------------------ registro COM/SolidWorks

        [ComRegisterFunction]
        public static void RegisterFunction(Type t)
        {
            using (var key = Registry.LocalMachine.CreateSubKey(
                $@"SOFTWARE\SolidWorks\Addins\{{{ADDIN_GUID}}}"))
            {
                key.SetValue(null, 0);
                key.SetValue("Title", TITLE);
                key.SetValue("Description", DESCRIPTION);
            }
            using (var key = Registry.CurrentUser.CreateSubKey(
                $@"Software\SolidWorks\AddInsStartup\{{{ADDIN_GUID}}}"))
            {
                key.SetValue(null, 1, RegistryValueKind.DWord);
            }
        }

        [ComUnregisterFunction]
        public static void UnregisterFunction(Type t)
        {
            Registry.LocalMachine.DeleteSubKeyTree(
                $@"SOFTWARE\SolidWorks\Addins\{{{ADDIN_GUID}}}", false);
            Registry.CurrentUser.DeleteSubKeyTree(
                $@"Software\SolidWorks\AddInsStartup\{{{ADDIN_GUID}}}", false);
        }
    }
}
