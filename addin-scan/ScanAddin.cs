// Add-in "Scan 3D" (Gromar) — engenharia reversa estilo QuickSurface.
// Aba própria no CommandManager; cada botão abre um PropertyManager nativo.
// O processamento roda no backend local (python -m swmcp.chat) e no motor
// swengine (WSL/venv).

using System;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swpublished;

namespace SwScanAddin
{
    [ComVisible(true)]
    [Guid(ADDIN_GUID)]
    public class ScanAddin : ISwAddin
    {
        public const string ADDIN_GUID = "3F8C2A17-9D54-4B6E-A81C-52ED7B90F3A1";
        private const string TITLE = "Scan 3D";
        private const string DESCRIPTION =
            "Engenharia reversa Gromar: scan 3D -> sólido (primitivas, seções, freeform, desvio)";
        private const string BACKEND_URL = "http://127.0.0.1:8765/";
        private const int CMD_GROUP_ID = 51;

        private ISldWorks? _app;
        private int _cookie;
        private System.Diagnostics.Process? _backend;
        private ICommandManager? _cmdMgr;
        private SldWorks? _swEventos;
        private bool _docTrocou;
        private readonly System.Collections.Generic.HashSet<int> _abaDevolvida = new();

        // (título, dica) — ordem = índice na tira de ícones
        private static readonly (string Nome, string Dica)[] CMDS =
        {
            ("Importar scan", "Importar malha do scanner (STL/OBJ/PLY)"),
            ("Exportar", "Exportar a malha ativa (STL/OBJ/PLY)"),
            ("Decimar", "Reduzir a quantidade de triângulos"),
            ("Info da malha", "Vértices, faces e dimensões"),
            ("Inverter normais", "Inverter a orientação da malha"),
            ("Seleção de malha", "Segmentar regiões usinadas × fundidas"),
            ("Alinhar por referências", "Alinhar o scan aos eixos"),
            ("Plano de simetria", "Detectar o plano de simetria da peça"),
            ("Primitivas", "Ajustar plano/cilindro/esfera/cone"),
            ("Superfície automática", "Freeform -> STEP"),
            ("Seção transversal", "Cortar o scan e desenhar no sketch"),
            ("Comparar", "Mapa de desvio scan × CAD"),
            ("Desenrolar", "Planificar chapa/tubo (roll-unroll)"),
            ("Viewport GL (teste)", "Liga/desliga o triângulo de teste OpenGL no viewport"),
        };

        public bool ConnectToSW(object thisSw, int cookie)
        {
            _app = (ISldWorks)thisSw;
            _cookie = cookie;
            _app.SetAddinCallbackInfo2(0, this, cookie);

            EnsureBackendRunning();
            CreateCommandTab();

            _swEventos = (SldWorks)thisSw;
            _swEventos.ActiveModelDocChangeNotify += AoTrocarDocumento;
            _swEventos.OnIdleNotify += AoFicarOcioso;
            return true;
        }

        public bool DisconnectFromSW()
        {
            if (_swEventos != null)
            {
                _swEventos.ActiveModelDocChangeNotify -= AoTrocarDocumento;
                _swEventos.OnIdleNotify -= AoFicarOcioso;
                _swEventos = null;
            }
            try { _cmdMgr?.RemoveCommandGroup2(CMD_GROUP_ID, true); } catch { }
            // o python.exe do venv é um lançador que cria outro python: mata a árvore
            try
            {
                if (_backend != null && !_backend.HasExited)
                    System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = "taskkill",
                        Arguments = "/T /F /PID " + _backend.Id,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                    })?.WaitForExit(5000);
            }
            catch { }
            _backend = null;
            _app = null;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            return true;
        }

        private void CreateCommandTab()
        {
            _cmdMgr = _app!.GetCommandManager(_cookie);
            var dir = Path.GetDirectoryName(typeof(ScanAddin).Assembly.Location) ?? "";
            int errors = 0;
            var group = _cmdMgr.CreateCommandGroup2(
                CMD_GROUP_ID, TITLE, DESCRIPTION, "Comandos de engenharia reversa",
                -1, true, ref errors);
            group.SmallIconList = Path.Combine(dir, "toolbar16.bmp");
            group.LargeIconList = Path.Combine(dir, "toolbar24.bmp");
            group.SmallMainIcon = Path.Combine(dir, "scan-icon.bmp");
            group.LargeMainIcon = Path.Combine(dir, "scan-icon-32.bmp");

            var ids = new int[CMDS.Length];
            for (int i = 0; i < CMDS.Length; i++)
            {
                ids[i] = group.AddCommandItem2(
                    CMDS[i].Nome, -1, CMDS[i].Dica, CMDS[i].Nome, i,
                    "OnCmd" + i, "", i,
                    (int)(swCommandItemType_e.swMenuItem | swCommandItemType_e.swToolbarItem));
            }
            group.HasToolbar = true;
            group.HasMenu = true;
            group.Activate();

            var cmdIds = new int[CMDS.Length];
            var styles = new int[CMDS.Length];
            for (int i = 0; i < CMDS.Length; i++)
            {
                cmdIds[i] = group.CommandID[ids[i]];
                styles[i] = (int)swCommandTabButtonTextDisplay_e
                    .swCommandTabButton_TextBelow;
            }

            // aba no CommandManager (como o QuickSurface) para peça e montagem.
            // Recria a cada carga: no SW 2023 a aba que ele restaura do registro
            // não é desenhada na fita (fica fantasma) se for reaproveitada.
            foreach (var docType in new[] { (int)swDocumentTypes_e.swDocPART,
                                            (int)swDocumentTypes_e.swDocASSEMBLY })
            {
                // remove a aba de cargas anteriores, senão os botões duplicam
                var existente = _cmdMgr.GetCommandTab(docType, TITLE);
                if (existente != null) _cmdMgr.RemoveCommandTab(existente);
                var tab = _cmdMgr.AddCommandTab(docType, TITLE);
                if (tab == null) continue;
                tab.AddCommandTabBox().AddCommands(cmdIds, styles);
            }
        }

        // Aba recém-criada nasce selecionada: no 1º documento de cada tipo da
        // sessão, depois que o SW termina de montar a fita (ocioso), devolve a
        // seleção para a primeira aba nativa (Recursos / Montagem).
        private int AoTrocarDocumento()
        {
            _docTrocou = true;
            return 0;
        }

        private int AoFicarOcioso()
        {
            if (!_docTrocou) return 0;
            _docTrocou = false;
            try
            {
                if (_app?.IActiveDoc2 is not ModelDoc2 doc) return 0;
                int tipo = doc.GetType();
                if (tipo != (int)swDocumentTypes_e.swDocPART &&
                    tipo != (int)swDocumentTypes_e.swDocASSEMBLY) return 0;
                if (_abaDevolvida.Add(tipo)) SelecionaPrimeiraAba(tipo);
            }
            catch { }
            return 0;
        }

        private void SelecionaPrimeiraAba(int docType)
        {
            // o CommandManager deste add-in só enxerga as próprias abas; as
            // nativas aparecem pelo de qualquer outro cookie
            for (int ck = 1; ck < 64; ck++)
            {
                if (ck == _cookie) continue;
                try
                {
                    if (_app!.GetCommandManager(ck)?.CommandTabs(docType) is not object[] tabs ||
                        tabs.Length < 2) continue;
                    var primeira = (CommandTab)tabs[0];
                    if (primeira.Name == TITLE) continue;
                    primeira.Active = true;
                    return;
                }
                catch { }
            }
        }

        // ------------------------------------------- fluxo nativo (M2S-like)
        private static System.Collections.Generic.Dictionary<string, object> J(
            params object[] kv)
        {
            var d = new System.Collections.Generic.Dictionary<string, object>();
            for (int i = 0; i + 1 < kv.Length; i += 2) d[(string)kv[i]] = kv[i + 1];
            return d;
        }

        private static object RegiaoAtiva() => J("active", true);

        private void Info(string titulo, string msg) =>
            _app!.SendMsgToUser2(titulo + "\n\n" + msg,
                (int)swMessageBoxIcon_e.swMbInformation,
                (int)swMessageBoxBtn_e.swMbOk);

        private void Erro(string titulo, Exception ex) =>
            _app!.SendMsgToUser2(titulo + " falhou:\n" + ex.Message,
                (int)swMessageBoxIcon_e.swMbWarning,
                (int)swMessageBoxBtn_e.swMbOk);

        // Importar: diálogo de arquivo -> import -> "Mesh Information"
        public void OnCmd0()
        {
            try
            {
                var p = Backend.Post("pick-file", J("kind", "mesh"));
                if (p["path"] == null) return;
                var r = Backend.Post("import", J("path", p["path"]!));
                Info("Informações da malha", Backend.Formatar(r,
                    "vertices", "faces", "extents_mm", "watertight",
                    "area_mm2", "volume_mm3", "aviso_unidade"));
            }
            catch (Exception ex) { Erro("Importar scan", ex); }
        }

        public void OnCmd1()
        {
            try
            {
                var r = Backend.Post("export");
                Info("Exportar", r.ContainsKey("cancelado")
                    ? "exportação cancelada" : "exportado: " + r["out"]);
            }
            catch (Exception ex) { Erro("Exportar", ex); }
        }

        public void OnCmd2() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Decimar",
            Dica = "Reduz a quantidade de triângulos da malha ativa.",
            Campos = new[]
            {
                new Campo { Tipo = "num", Rotulo = "Número de triângulos",
                            Chave = "target_faces", Valor = 200000,
                            Min = 1000, Max = 20000000 },
            },
            Executar = v =>
            {
                var r = Backend.Post("decimate",
                    J("target_faces", (int)(double)v["target_faces"]));
                return Backend.Formatar(r, "vertices", "faces", "extents_mm");
            },
        });

        public void OnCmd3()
        {
            try
            {
                Info("Informações da malha", Backend.Formatar(
                    Backend.Post("info"),
                    "vertices", "faces", "extents_mm", "watertight",
                    "area_mm2", "volume_mm3"));
            }
            catch (Exception ex) { Erro("Info da malha", ex); }
        }

        public void OnCmd4()
        {
            try
            {
                var r = Backend.Post("flip");
                Info("Inverter normais", "normais invertidas (" + r["faces"] + " faces)");
            }
            catch (Exception ex) { Erro("Inverter normais", ex); }
        }

        public void OnCmd5() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Seleção de malha",
            Dica = "Separa regiões usinadas (lisas) do bruto de fundição.",
            Campos = new[]
            {
                new Campo { Tipo = "num", Rotulo = "Limiar de curvatura (graus)",
                            Chave = "smooth_threshold_deg", Valor = 8,
                            Min = 2, Max = 30 },
            },
            Executar = v =>
            {
                var r = Backend.Post("segment", v);
                var regs = (object[])r["regioes_lisas"];
                return regs.Length + " regiões lisas encontradas · " +
                       r["vertices_rugosos"] + " vértices rugosos (fundição).";
            },
        });

        public void OnCmd6() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Alinhar por referências",
            Campos = new[]
            {
                new Campo { Tipo = "combo", Rotulo = "Modo", Chave = "mode",
                            Opcoes = new[] { "Eixos principais (PCA)",
                                             "Caixa mínima orientada",
                                             "Assentar região ativa no XY" },
                            ValoresOpcoes = new object[] { "pca", "bbox",
                                                           "plane_to_xy" } },
            },
            Executar = v =>
            {
                var corpo = J("mode", v["mode"]);
                if ((string)v["mode"] == "plane_to_xy")
                    corpo["region"] = RegiaoAtiva();
                var r = Backend.Post("align", corpo);
                return "alinhado (" + v["mode"] + ")\n" +
                       Backend.Formatar(r, "extents_mm");
            },
        });

        public void OnCmd7()
        {
            try
            {
                var r = Backend.Post("symmetry");
                Info("Plano de simetria",
                    ((bool)r["simetrica"] ? "✔ peça simétrica" : "✖ simetria fraca")
                    + "\n" + Backend.Formatar(r, "score_mm", "limite_mm",
                                              "normal", "point", "aviso"));
            }
            catch (Exception ex) { Erro("Plano de simetria", ex); }
        }

        public void OnCmd8() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Primitivas",
            Dica = "Ajusta na malha inteira.",
            Campos = new[]
            {
                new Campo { Tipo = "combo", Rotulo = "Tipo", Chave = "kind",
                            Opcoes = new[] { "Automático", "Plano", "Cilindro",
                                             "Esfera", "Cone" },
                            ValoresOpcoes = new object[] { "auto", "plane",
                                "cylinder", "sphere", "cone" } },
                new Campo { Tipo = "num", Rotulo = "Tolerância (mm)",
                            Chave = "tolerance_mm", Valor = 0.15,
                            Min = 0.01, Max = 5 },
                new Campo { Tipo = "combo", Rotulo = "Restringir eixo/normal",
                            Chave = "eixo",
                            Opcoes = new[] { "Livre (best fit)", "Eixo X",
                                             "Eixo Y", "Eixo Z" },
                            ValoresOpcoes = new object[] { "", "x", "y", "z" } },
                new Campo { Tipo = "check", Rotulo = "Criar no SolidWorks",
                            Chave = "criar", Marcado = true },
            },
            Executar = v =>
            {
                var corpo = J("kind", v["kind"],
                              "tolerance_mm", v["tolerance_mm"],
                              "region", RegiaoAtiva());
                var eixo = (string)v["eixo"];
                if (eixo != "")
                    corpo["constraint_axis"] = eixo == "x"
                        ? new object[] { 1, 0, 0 }
                        : eixo == "y" ? new object[] { 0, 1, 0 }
                                      : new object[] { 0, 0, 1 };
                var r = Backend.Post("fit", corpo);
                var texto = Backend.Formatar(r, "kind", "inlier_fraction",
                    "rms_mm", "radius", "height", "half_angle_deg",
                    "normal", "axis", "point", "center");
                if ((bool)v["criar"])
                {
                    var sw = Backend.Post("primitive-sw", J("primitive", r));
                    texto += "\n\nno SolidWorks:\n" + Backend.Formatar(sw,
                        "feature", "sketch", "base", "offset_mm",
                        "diametro_mm", "altura_para_extrudar_mm", "aviso");
                }
                return texto;
            },
        });

        public void OnCmd9() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Superfície automática",
            Dica = "B-spline na região ativa; o STEP resultante importa no " +
                   "SolidWorks e serve de ferramenta de recorte.",
            Campos = new[]
            {
                new Campo { Tipo = "num", Rotulo = "Grade U", Chave = "grid_u",
                            Valor = 40, Min = 10, Max = 120 },
                new Campo { Tipo = "num", Rotulo = "Grade V", Chave = "grid_v",
                            Valor = 40, Min = 10, Max = 120 },
                new Campo { Tipo = "num", Rotulo = "Tolerância (mm)",
                            Chave = "tol_mm", Valor = 0.05, Min = 0.01, Max = 2 },
                new Campo { Tipo = "num", Rotulo = "Estender bordas (mm)",
                            Chave = "extend_mm", Valor = 5, Min = 0, Max = 100 },
            },
            Executar = v =>
            {
                v["region"] = RegiaoAtiva();
                v["grid_u"] = (int)(double)v["grid_u"];
                v["grid_v"] = (int)(double)v["grid_v"];
                var r = Backend.Post("freeform", v);
                return "STEP: " + r["step"] + "\n" + Backend.Formatar(r,
                    "desvio_rms_mm", "desvio_p95_mm", "desvio_max_mm",
                    "cobertura_grade", "aviso");
            },
        });

        public void OnCmd10() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Seção transversal",
            Dica = "Abra antes um sketch no plano correspondente ao corte.",
            Campos = new[]
            {
                new Campo { Tipo = "combo", Rotulo = "Eixo", Chave = "axis",
                            Opcoes = new[] { "Z", "X", "Y" },
                            ValoresOpcoes = new object[] { "z", "x", "y" } },
                new Campo { Tipo = "num", Rotulo = "Cota (mm)",
                            Chave = "position_mm", Valor = 0,
                            Min = -100000, Max = 100000 },
                new Campo { Tipo = "num", Rotulo = "Tolerância (mm)",
                            Chave = "tol_mm", Valor = 0.1, Min = 0.01, Max = 2 },
            },
            Executar = v =>
            {
                var r = Backend.Post("section-sketch", v);
                if (r.ContainsKey("aviso") && r["aviso"] != null)
                    return (string)r["aviso"];
                return "desenhado no sketch ativo:\n" +
                       Backend.Formatar(r, "desenhado", "loops",
                                        "formas_reconhecidas");
            },
        });

        public void OnCmd11() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Comparar (desvio)",
            Dica = "Escolha o STL do modelo reconstruído após o OK. O mapa " +
                   "colorido sai em PNG.",
            Campos = new[]
            {
                new Campo { Tipo = "check", Rotulo = "Modo Passa/Falha",
                            Chave = "pf", Marcado = true },
                new Campo { Tipo = "num", Rotulo = "Tolerância ± (mm)",
                            Chave = "tol", Valor = 0.1, Min = 0.01, Max = 5 },
            },
            Executar = v =>
            {
                var p = Backend.Post("pick-file", J("kind", "mesh"));
                if (p["path"] == null) return "cancelado";
                var corpo = J("reference_stl", p["path"]!);
                if ((bool)v["pf"]) corpo["pass_fail_tol_mm"] = v["tol"];
                var r = Backend.Post("deviation", corpo);
                return Backend.Formatar(r, "cobertura", "rms_mm",
                    "p95_abs_mm", "dentro_tolerancia") +
                    "\n\nPNG do mapa: " + r["png"];
            },
        });

        public void OnCmd12() => Pmp.Mostrar(_app!, new PaginaCmd
        {
            Titulo = "Desenrolar",
            Dica = "Planifica a região ativa (chapa/tubo/cone).",
            Campos = new[]
            {
                new Campo { Tipo = "combo", Rotulo = "Método", Chave = "method",
                            Opcoes = new[] { "Automático", "Cilindro", "Cone",
                                             "Genérico (LSCM)" },
                            ValoresOpcoes = new object[] { "auto", "cylinder",
                                "cone", "lscm" } },
                new Campo { Tipo = "num", Rotulo = "Costura (graus)",
                            Chave = "seam_deg", Valor = 0, Min = 0, Max = 360 },
                new Campo { Tipo = "check",
                            Rotulo = "Desenhar sketch de corte no SolidWorks",
                            Chave = "sk", Marcado = true },
            },
            Executar = v =>
            {
                var rota = (bool)v["sk"] ? "unroll-sketch" : "unroll";
                var r = Backend.Post(rota, J("method", v["method"],
                    "seam_deg", v["seam_deg"], "region", RegiaoAtiva()));
                return Backend.Formatar(r, "metodo", "dimensoes_mm",
                    "area_3d_mm2", "area_plana_mm2", "distorcao_media_pct",
                    "distorcao_max_pct", "desenhado", "aviso");
            },
        });

        private readonly GlOverlay _overlay = new GlOverlay();

        public void OnCmd13()
        {
            string msg = _overlay.Active ? _overlay.Disable() : _overlay.Enable(_app!);
            string extra = "";
            try
            {
                // lê o Enhanced Graphics Performance se o enum existir nesta versão
                var t = typeof(swUserPreferenceToggle_e);
                foreach (var nome in new[] { "swPerformanceEnhanceGraphicsPerformance",
                                             "swEnhancedGraphicsPerformance" })
                {
                    var campo = t.GetField(nome);
                    if (campo != null)
                    {
                        bool on = _app!.GetUserPreferenceToggle((int)campo.GetValue(null)!);
                        extra = $"\nEnhanced Graphics Performance: {(on ? "LIGADO" : "desligado")}";
                        break;
                    }
                }
            }
            catch { }
            _app!.SendMsgToUser2("Spike OpenGL: " + msg + extra +
                "\n\nTeste: gire a vista — o triângulo deve acompanhar o modelo " +
                "sem piscar. Repita com o Enhanced Graphics ligado E desligado " +
                "(Opções > Desempenho) e me diga o resultado.",
                (int)swMessageBoxIcon_e.swMbInformation,
                (int)swMessageBoxBtn_e.swMbOk);
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
                // bin\Release\SwScanAddin.dll -> solidworks-mcp\.venv
                var dll = typeof(ScanAddin).Assembly.Location;
                var raiz = Path.GetFullPath(Path.Combine(
                    Path.GetDirectoryName(dll) ?? ".", "..", "..", ".."));
                file = Path.Combine(raiz, ".venv", "Scripts", "python.exe");
                args = "-m swmcp.chat";
            }
            try
            {
                _backend = System.Diagnostics.Process.Start(
                    new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = file,
                        Arguments = args,
                        // ShellExecute: o backend NÃO herda os handles do
                        // SolidWorks. Com UseShellExecute=false ele herdava o
                        // diário (swxJRNL) e caches; órfão, travava o próximo SW.
                        UseShellExecute = true,
                        WindowStyle = System.Diagnostics.ProcessWindowStyle.Hidden,
                        WorkingDirectory = Path.GetDirectoryName(file) ?? ".",
                    });
                for (int i = 0; i < 20 && !BackendAlive(); i++)
                    System.Threading.Thread.Sleep(500);
            }
            catch
            {
                // sem backend os comandos avisam o erro ao serem usados
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
