// Controle WinForms com WebView2 apontando para o painel Scan 3D.
// Mesmo truque do add-in do chat: o SolidWorks reparenta a janela, então
// nada de evento Load — inicialização no construtor e resize por timer.

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SwScanAddin
{
    public class PanelControl : UserControl
    {
        private readonly WebView2 _webView;
        private readonly string _url;
        private readonly Timer _resizeTimer;
        private bool _ready;

        [DllImport("user32.dll")]
        private static extern IntPtr GetParent(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool GetClientRect(IntPtr hWnd, out RECT rect);

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT { public int Left, Top, Right, Bottom; }

        public PanelControl(string url)
        {
            _url = url;
            Size = new System.Drawing.Size(420, 800);
            _webView = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(_webView);
            _ = Handle.ToInt64();

            _resizeTimer = new Timer { Interval = 400 };
            _resizeTimer.Tick += (s, e) => FitToParent();
            _resizeTimer.Start();

            _ = InitAsync();
        }

        /// Navega para um grupo do painel (âncora #g-xxx) — usado pelos
        /// botões do CommandManager.
        public void ShowGroup(string anchor)
        {
            if (!_ready) return;
            try
            {
                _webView.CoreWebView2.ExecuteScriptAsync(
                    $"location.hash = '{anchor}'; " +
                    "window.dispatchEvent(new HashChangeEvent('hashchange'));");
            }
            catch { }
        }

        /// Pede ao painel para recarregar a malha no viewer 3D.
        public void Refresh3D()
        {
            if (!_ready) return;
            try
            {
                _webView.CoreWebView2.ExecuteScriptAsync(
                    "window.viewer && window.viewer.refreshViewer()");
            }
            catch { }
        }

        private void FitToParent()
        {
            var parent = GetParent(Handle);
            if (parent == IntPtr.Zero) return;
            if (!GetClientRect(parent, out var r)) return;
            if (r.Right > 0 && r.Bottom > 0 && (Width != r.Right || Height != r.Bottom))
                SetBounds(0, 0, r.Right, r.Bottom);
        }

        private async System.Threading.Tasks.Task InitAsync()
        {
            try
            {
                var dataDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SwScanAddin", "WebView2");
                var env = await CoreWebView2Environment.CreateAsync(null, dataDir);
                await _webView.EnsureCoreWebView2Async(env);
                _webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                _webView.CoreWebView2.Navigate(_url);
                _ready = true;
            }
            catch (Exception ex)
            {
                var label = new Label
                {
                    Dock = DockStyle.Fill,
                    Text = "Falha ao iniciar o WebView2: " + ex.Message +
                           "\n\nInstale o WebView2 Runtime da Microsoft e reative o add-in.",
                    Padding = new Padding(12),
                };
                Controls.Clear();
                Controls.Add(label);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _resizeTimer.Dispose();
                _webView.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
