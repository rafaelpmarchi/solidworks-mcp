// Cliente HTTP do backend local (python -m swmcp.chat) para os comandos
// nativos: POST /mesh/<rota> com JSON, resposta como dicionário.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Web.Script.Serialization;

namespace SwScanAddin
{
    public static class Backend
    {
        private const string BASE = "http://127.0.0.1:8765/mesh/";
        private static readonly JavaScriptSerializer Json =
            new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };

        public static Dictionary<string, object> Post(string rota,
            Dictionary<string, object>? corpo = null, int timeoutMs = 600000)
        {
            var req = (HttpWebRequest)WebRequest.Create(BASE + rota);
            req.Method = "POST";
            req.ContentType = "application/json";
            req.Timeout = timeoutMs;
            var dados = Encoding.UTF8.GetBytes(
                Json.Serialize(corpo ?? new Dictionary<string, object>()));
            using (var s = req.GetRequestStream()) s.Write(dados, 0, dados.Length);
            string texto;
            try
            {
                using var resp = (HttpWebResponse)req.GetResponse();
                using var r = new StreamReader(resp.GetResponseStream());
                texto = r.ReadToEnd();
            }
            catch (WebException ex) when (ex.Response != null)
            {
                using var r = new StreamReader(ex.Response.GetResponseStream());
                texto = r.ReadToEnd();
            }
            var dict = (Dictionary<string, object>)Json.DeserializeObject(texto);
            if (dict.TryGetValue("error", out var erro))
                throw new InvalidOperationException(erro?.ToString() ?? "erro");
            return dict;
        }

        /// Formata um resultado como texto legível para o diálogo (estilo
        /// "Mesh Information" do Mesh2Surface).
        public static string Formatar(Dictionary<string, object> d,
                                      params string[] chaves)
        {
            var sb = new StringBuilder();
            var lista = chaves.Length > 0 ? chaves : new List<string>(d.Keys).ToArray();
            foreach (var k in lista)
            {
                if (!d.TryGetValue(k, out var v) || v == null) continue;
                sb.Append(k).Append(": ").Append(Texto(v)).Append('\n');
            }
            return sb.ToString().TrimEnd('\n');
        }

        private static string Texto(object v)
        {
            if (v is object[] arr)
            {
                var partes = new List<string>();
                foreach (var x in arr) partes.Add(Texto(x));
                return "[" + string.Join(", ", partes) + "]";
            }
            if (v is Dictionary<string, object> d) return Formatar(d);
            return Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture) ?? "";
        }
    }
}
