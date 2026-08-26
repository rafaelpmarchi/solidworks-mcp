// Controle WinForms com WebView2 apontando para o backend local do chat.
//
// Atenção: o SolidWorks reparenta esta janela via DisplayWindowFromHandlex64,
// então o evento Load do WinForms nunca dispara — a inicialização do WebView2
// é feita explicitamente no construtor, e o tamanho é acompanhado por timer
// (o taskpane não repassa WM_SIZE ao filho reparentado).

using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SwClaudeAddin
{
    public class ChatControl : UserControl
    {
        private readonly WebView2 _webView;
        private readonly string _url;
        private readonly Timer _resizeTimer;

        [DllImport("user32.dll")]
        private static extern IntPtr GetParent(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool GetClientRect(IntPtr hWnd, out RECT rect);

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT { public int Left, Top, Right, Bottom; }

        public ChatControl(string url)
        {
            _url = url;
            Size = new System.Drawing.Size(400, 800);
            _webView = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(_webView);
            _ = Handle.ToInt64(); // força criação do handle antes do DisplayWindowFromHandle

            _resizeTimer = new Timer { Interval = 400 };
            _resizeTimer.Tick += (s, e) => FitToParent();
            _resizeTimer.Start();

            // não depende do Load: inicia já
            _ = InitAsync();
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
                    "SwClaudeAddin", "WebView2");
                var env = await CoreWebView2Environment.CreateAsync(null, dataDir);
                await _webView.EnsureCoreWebView2Async(env);
                _webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                _webView.CoreWebView2.Navigate(_url);
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
