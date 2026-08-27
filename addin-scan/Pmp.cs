// PropertyManager nativo (painel esquerdo com ✓/✗) para os comandos do
// Scan 3D — a dinâmica do Mesh2Surface: botão do ribbon abre a página de
// parâmetros; OK executa no backend e mostra o resultado num diálogo.

using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swpublished;

namespace SwScanAddin
{
    // ---------------------------------------------------------- definição
    public class Campo
    {
        public string Tipo = "num";      // num | combo | check
        public string Rotulo = "";
        public string Chave = "";        // chave no JSON enviado ao backend
        public double Valor;
        public double Min;
        public double Max = 1e6;
        public string[] Opcoes = Array.Empty<string>();
        public object[]? ValoresOpcoes;  // valor por opção (combo)
        public int Selecionado;
        public bool Marcado;
    }

    public class PaginaCmd
    {
        public string Titulo = "";
        public string Dica = "";
        public Campo[] Campos = Array.Empty<Campo>();
        public Func<Dictionary<string, object>, string> Executar = _ => "";
    }

    // ------------------------------------------------------------ handler
    public class PmpHandler : IPropertyManagerPage2Handler9
    {
        private readonly ISldWorks _app;
        private readonly PaginaCmd _pagina;
        private readonly Dictionary<int, IPropertyManagerPageControl> _ctl;
        private readonly Campo[] _campos;
        private bool _ok;

        public PmpHandler(ISldWorks app, PaginaCmd pagina, Campo[] campos,
                          Dictionary<int, IPropertyManagerPageControl> ctl)
        {
            _app = app; _pagina = pagina; _campos = campos; _ctl = ctl;
        }

        public void OnClose(int Reason)
        {
            _ok = Reason == (int)swPropertyManagerPageCloseReasons_e
                .swPropertyManagerPageClose_Okay;
            if (!_ok) return;
            // lê os valores AGORA (os controles morrem depois do AfterClose)
            for (int i = 0; i < _campos.Length; i++)
            {
                var c = _campos[i];
                var ctl = _ctl[i];
                if (c.Tipo == "num")
                    c.Valor = ((IPropertyManagerPageNumberbox)ctl).Value;
                else if (c.Tipo == "combo")
                    c.Selecionado = ((IPropertyManagerPageCombobox)ctl).CurrentSelection;
                else if (c.Tipo == "check")
                    c.Marcado = ((IPropertyManagerPageCheckbox)ctl).Checked;
            }
        }

        public void AfterClose()
        {
            if (!_ok) return;
            var valores = new Dictionary<string, object>();
            foreach (var c in _campos)
            {
                if (string.IsNullOrEmpty(c.Chave)) continue;
                if (c.Tipo == "num") valores[c.Chave] = c.Valor;
                else if (c.Tipo == "check") valores[c.Chave] = c.Marcado;
                else if (c.Tipo == "combo")
                    valores[c.Chave] = c.ValoresOpcoes != null
                        ? c.ValoresOpcoes[c.Selecionado]
                        : c.Opcoes[c.Selecionado];
            }
            try
            {
                var msg = _pagina.Executar(valores);
                _app.SendMsgToUser2(_pagina.Titulo + "\n\n" + msg,
                    (int)swMessageBoxIcon_e.swMbInformation,
                    (int)swMessageBoxBtn_e.swMbOk);
            }
            catch (Exception ex)
            {
                _app.SendMsgToUser2(_pagina.Titulo + " falhou:\n" + ex.Message,
                    (int)swMessageBoxIcon_e.swMbWarning,
                    (int)swMessageBoxBtn_e.swMbOk);
            }
        }

        // ---- restante da interface: sem uso neste fluxo
        public void AfterActivation() { }
        public bool OnHelp() => false;
        public bool OnPreviousPage() => false;
        public bool OnNextPage() => false;
        public bool OnPreview() => false;
        public void OnWhatsNew() { }
        public void OnUndo() { }
        public void OnRedo() { }
        public bool OnTabClicked(int Id) => false;
        public void OnGroupExpand(int Id, bool Expanded) { }
        public void OnGroupCheck(int Id, bool Checked) { }
        public void OnCheckboxCheck(int Id, bool Checked) { }
        public void OnOptionCheck(int Id) { }
        public void OnButtonPress(int Id) { }
        public void OnTextboxChanged(int Id, string Text) { }
        public void OnNumberboxChanged(int Id, double Value) { }
        public void OnComboboxEditChanged(int Id, string Text) { }
        public void OnComboboxSelectionChanged(int Id, int Item) { }
        public void OnListboxSelectionChanged(int Id, int Item) { }
        public void OnSelectionboxFocusChanged(int Id) { }
        public void OnSelectionboxListChanged(int Id, int Count) { }
        public void OnSelectionboxCalloutCreated(int Id) { }
        public void OnSelectionboxCalloutDestroyed(int Id) { }
        public bool OnSubmitSelection(int Id, object Selection, int SelType,
                                      ref string ItemText) => true;
        public int OnActiveXControlCreated(int Id, bool Status) => 0;
        public void OnSliderPositionChanged(int Id, double Value) { }
        public void OnSliderTrackingCompleted(int Id, double Value) { }
        public void OnGainedFocus(int Id) { }
        public void OnLostFocus(int Id) { }
        public int OnWindowFromHandleControlCreated(int Id, bool Status) => 0;
        public void OnListboxRMBUp(int Id, int PosX, int PosY) { }
        public void OnNumberBoxTrackingCompleted(int Id, double Value) { }
        public bool OnKeystroke(int Wparam, int Message, int Lparam, int Id)
            => false;
        public void OnPopupMenuItem(int Id) { }
        public void OnPopupMenuItemUpdate(int Id, ref int retval) { }
        public void OnLockedSelectionChanged(int Id, int Count) { }
        public void OnComboboxSelectionChangedList(int Id, int Item) { }
    }

    // ------------------------------------------------------------ builder
    public static class Pmp
    {
        // páginas vivas (o GC não pode recolher enquanto abertas)
        private static readonly List<object> Vivas = new List<object>();

        public static void Mostrar(ISldWorks app, PaginaCmd pagina)
        {
            var ctl = new Dictionary<int, IPropertyManagerPageControl>();
            var handler = new PmpHandler(app, pagina, pagina.Campos, ctl);
            int erros = 0;
            var page = (IPropertyManagerPage2)app.CreatePropertyManagerPage(
                pagina.Titulo,
                (int)(swPropertyManagerPageOptions_e.swPropertyManagerOptions_OkayButton
                    | swPropertyManagerPageOptions_e.swPropertyManagerOptions_CancelButton),
                handler, ref erros);
            var grupo = (IPropertyManagerPageGroup)page.AddGroupBox(1000,
                "Parâmetros",
                (int)(swAddGroupBoxOptions_e.swGroupBoxOptions_Visible
                    | swAddGroupBoxOptions_e.swGroupBoxOptions_Expanded));
            if (!string.IsNullOrEmpty(pagina.Dica))
                page.SetMessage3(pagina.Dica,
                    (int)swPropertyManagerPageMessageVisibility.swMessageBoxVisible,
                    (int)swPropertyManagerPageMessageExpanded.swMessageBoxExpand,
                    "");

            for (int i = 0; i < pagina.Campos.Length; i++)
            {
                var c = pagina.Campos[i];
                short tipo = c.Tipo switch
                {
                    "num" => (short)swPropertyManagerPageControlType_e.swControlType_Numberbox,
                    "combo" => (short)swPropertyManagerPageControlType_e.swControlType_Combobox,
                    _ => (short)swPropertyManagerPageControlType_e.swControlType_Checkbox,
                };
                var pc = (IPropertyManagerPageControl)grupo.AddControl2((short)i,
                    tipo, c.Rotulo,
                    (short)swPropertyManagerPageControlLeftAlign_e.swControlAlign_LeftEdge,
                    (int)(swAddControlOptions_e.swControlOptions_Visible
                        | swAddControlOptions_e.swControlOptions_Enabled),
                    c.Rotulo);
                if (c.Tipo == "num")
                {
                    var nb = (IPropertyManagerPageNumberbox)pc;
                    nb.SetRange2((int)swNumberboxUnitType_e.swNumberBox_UnitlessDouble,
                                 c.Min, c.Max, true, 0.01, 1.0, 0.1);
                    nb.Value = c.Valor;
                }
                else if (c.Tipo == "combo")
                {
                    var cb = (IPropertyManagerPageCombobox)pc;
                    cb.AddItems(c.Opcoes);
                    cb.CurrentSelection = (short)c.Selecionado;
                }
                else
                {
                    ((IPropertyManagerPageCheckbox)pc).Checked = c.Marcado;
                }
                ctl[i] = pc;
            }
            Vivas.Add(page);
            Vivas.Add(handler);
            if (Vivas.Count > 20) Vivas.RemoveRange(0, Vivas.Count - 8);
            page.Show2(0);
        }
    }
}
