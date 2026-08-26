// Controle WinForms com WebView2 apontando para o backend local do chat.

using System;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SwClaudeAddin
{
    public class ChatControl : UserControl
    {
        private readonly WebView2 _webView;
        private readonly string _url;

        public ChatControl(string url)
        {
            _url = url;
            _webView = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(_webView);
            // força a criação do handle antes do DisplayWindowFromHandle
            var _ = Handle;
            Load += async (_, __) => await InitAsync();
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
    }
}
