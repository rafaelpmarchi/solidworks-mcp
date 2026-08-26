"""Gera os formatos de folha (.slddrt) padrão Gromar para A4..A0.

Layout inspirado no desenho-cobaia do cliente HINE (9-8126.A): moldura com
zonas alfanuméricas, marcas de centro, tabela de revisões no topo-direito e
legenda no canto inferior-direito — porém em português e com o logo Gromar.

Uso:
    python tools/gerar_formatos_gromar.py --only a3 --dest <pasta>
    python tools/gerar_formatos_gromar.py --dest <pasta>

Tudo aqui é milímetro; a conversão para metro (unidade da API) fica no ``m()``.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from swmcp.com.session import SwSession, cast_to, swconst  # noqa: E402

# PNG com fundo recortado (gerado por tools/logo_transparente.py a partir do JPG
# oficial) — o JPG entra na legenda como um retângulo branco
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "logo-gromar.png")

SEM_LOGO = False  # ligado por --sem-logo (diagnóstico)

# ----------------------------------------------------------------- formatos


@dataclass(frozen=True)
class Formato:
    nome: str          # sufixo do arquivo .slddrt
    rotulo: str        # o que vai escrito no campo FORMATO
    largura: float     # mm
    altura: float      # mm
    colunas: int       # divisões de zona no sentido horizontal
    linhas: int        # divisões de zona no sentido vertical
    zonas: bool = True # A4 dispensa faixa de zonas (ISO 5457) — e não teria largura para ela


FORMATOS = {
    "a4v": Formato("A4 - retrato - gromar", "A4", 210.0, 297.0, 3, 4, zonas=False),
    "a4": Formato("A4 - paisagem - gromar", "A4", 297.0, 210.0, 4, 3, zonas=False),
    "a3": Formato("A3 - gromar", "A3", 420.0, 297.0, 6, 4),
    "a2": Formato("A2 - gromar", "A2", 594.0, 420.0, 8, 6),
    "a1": Formato("A1 - gromar", "A1", 841.0, 594.0, 12, 8),
    "a0": Formato("A0 - gromar", "A0", 1189.0, 841.0, 16, 12),
}

MARGEM_ESQ = 20.0   # margem larga para arquivamento (ISO 5457)
MARGEM = 10.0
FAIXA = 5.0         # largura da faixa de zonas, medida para dentro da moldura

LEG_L = 180.0       # legenda: largura padrão ISO 7200
LEG_H = 62.0

# alturas de texto (mm)
H_ROTULO = 1.8
H_VALOR = 3.2
H_TITULO = 5.0
H_DESTAQUE = 6.5
H_ZONA = 3.5

def m(mm: float) -> float:
    return mm / 1000.0


# ------------------------------------------------------------------ desenho


class Folha:
    """Acumula linhas e notas em mm e despeja no documento aberto."""

    def __init__(self, model, sw):
        self.model = model
        self.sm = model.SketchManager
        self.sw = sw
        # sem isto o SW infere relações (horizontal/vertical/coincidente) e
        # deforma o traçado — o formato tem de sair exatamente como calculado
        self.sm.AddToDB = True
        self.sm.DisplayWhenAdded = False

    def encerrar(self) -> None:
        self.sm.AddToDB = False
        self.sm.DisplayWhenAdded = True

    def linha(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.sm.CreateLine(m(x1), m(y1), 0.0, m(x2), m(y2), 0.0)

    def _segmentos(self):
        sk = self.sm.ActiveSketch
        if sk is None:
            return []
        return list(cast_to(sk, "ISketch").GetSketchSegments() or ())

    def ids_dos_segmentos(self) -> set:
        return {tuple(cast_to(s, "ISketchSegment").GetID()) for s in self._segmentos()}

    def remover_segmentos_novos(self, antes: set) -> int:
        removidos = 0
        for raw in self._segmentos():
            seg = cast_to(raw, "ISketchSegment")
            if tuple(seg.GetID()) in antes:
                continue
            seg.Select4(False, None)
            self.model.EditDelete()
            removidos += 1
        self.model.ClearSelection2(True)
        return removidos

    def circulo(self, xc: float, yc: float, raio: float) -> None:
        self.sm.CreateCircleByRadius(m(xc), m(yc), 0.0, m(raio))

    def retangulo(self, x: float, y: float, larg: float, alt: float) -> None:
        self.linha(x, y, x + larg, y)
        self.linha(x + larg, y, x + larg, y + alt)
        self.linha(x + larg, y + alt, x, y + alt)
        self.linha(x, y + alt, x, y)

    def nota(
        self,
        texto: str,
        x: float,
        y: float,
        altura: float = H_VALOR,
        just: str = "left",
        negrito: bool = False,
    ) -> None:
        """Insere nota; (x, y) é a linha de base do texto, na justificação pedida.

        A API ancora a nota pelo topo do bloco: a base do texto cai ~1,13×
        CharHeight abaixo do ponto passado (medido em calibração).
        """
        y = y + 1.133 * altura
        # sem isto o SW pendura uma linha indicativa na entidade selecionada
        self.model.ClearSelection2(True)
        raw = self.model.InsertNote(texto)
        if raw is None:
            raise RuntimeError(f"InsertNote falhou para {texto!r}")
        note = cast_to(raw, "INote")  # late binding não expõe os membros de INote
        just_id = {
            "left": self.sw.swTextJustificationLeft,
            "center": self.sw.swTextJustificationCenter,
            "right": self.sw.swTextJustificationRight,
        }[just]
        note.SetTextJustification(just_id)
        note.SetBalloon(self.sw.swBS_None, 0)
        ann = cast_to(note.GetAnnotation(), "IAnnotation")
        ann.SetLeader3(self.sw.swNO_LEADER, 0, False, False, False, False)
        ann.SetPosition(m(x), m(y), 0.0)
        fmt = cast_to(ann.GetTextFormat(0), "ITextFormat")
        fmt.CharHeight = m(altura)
        fmt.Bold = negrito
        ann.SetTextFormat(0, False, fmt)
        self.model.ClearSelection2(True)

    def rotulo_campo(self, texto: str, x: float, y: float) -> None:
        """Rótulo pequeno no canto superior-esquerdo de uma célula."""
        self.nota(texto, x + 1.2, y - 1.0 - H_ROTULO, altura=H_ROTULO)


def area_util(fm: Formato) -> tuple[float, float, float, float]:
    """Retângulo onde legenda e tabela de revisões encostam (por dentro das zonas)."""
    recuo = FAIXA if fm.zonas else 0.0
    return (
        MARGEM_ESQ + recuo,
        MARGEM + recuo,
        fm.largura - MARGEM - recuo,
        fm.altura - MARGEM - recuo,
    )


def simbolo_projecao(f: Folha, xc: float, yc: float, h: float = 6.0) -> None:
    """Símbolo do 1º diedro (ISO-E): cone em corte à esquerda, círculos à direita."""
    comp = h
    menor = h / 2
    # trapézio (vista frontal do cone) com a base menor voltada para os círculos
    x0 = xc - comp - h * 0.45
    x1 = x0 + comp
    f.linha(x0, yc - h / 2, x0, yc + h / 2)
    f.linha(x1, yc - menor / 2, x1, yc + menor / 2)
    f.linha(x0, yc + h / 2, x1, yc + menor / 2)
    f.linha(x0, yc - h / 2, x1, yc - menor / 2)
    # vista lateral: círculos concêntricos
    cx = xc + h * 0.45 + h / 2
    f.circulo(cx, yc, h / 2)
    f.circulo(cx, yc, menor / 2)


def moldura(f: Folha, fm: Formato) -> None:
    x0, y0 = MARGEM_ESQ, MARGEM
    x1, y1 = fm.largura - MARGEM, fm.altura - MARGEM

    # borda externa fina + moldura interna (a que delimita a área útil)
    f.retangulo(5.0, 5.0, fm.largura - 10.0, fm.altura - 10.0)
    f.retangulo(x0, y0, x1 - x0, y1 - y0)

    if not fm.zonas:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        f.linha(mx, 5.0, mx, y0)
        f.linha(mx, y1, mx, fm.altura - 5.0)
        f.linha(5.0, my, x0, my)
        f.linha(x1, my, fm.largura - 5.0, my)
        return

    # trilho interno das zonas
    f.retangulo(x0 + FAIXA, y0 + FAIXA, (x1 - x0) - 2 * FAIXA, (y1 - y0) - 2 * FAIXA)

    passo_x = (x1 - x0) / fm.colunas
    passo_y = (y1 - y0) / fm.linhas

    for i in range(1, fm.colunas):
        x = x0 + i * passo_x
        f.linha(x, y0, x, y0 + FAIXA)
        f.linha(x, y1 - FAIXA, x, y1)
    for i in range(1, fm.linhas):
        y = y0 + i * passo_y
        f.linha(x0, y, x0 + FAIXA, y)
        f.linha(x1 - FAIXA, y, x1, y)

    # números crescem da esquerda para a direita; letras de cima para baixo
    for i in range(fm.colunas):
        cx = x0 + (i + 0.5) * passo_x
        for cy in (y0 + FAIXA / 2, y1 - FAIXA / 2):
            f.nota(str(i + 1), cx, cy - H_ZONA / 2, altura=H_ZONA, just="center")
    for i in range(fm.linhas):
        cy = y1 - (i + 0.5) * passo_y - H_ZONA / 2
        letra = chr(ord("A") + i)
        for cx in (x0 + FAIXA / 2, x1 - FAIXA / 2):
            f.nota(letra, cx, cy, altura=H_ZONA, just="center")

    # marcas de centro dos quatro lados (dobra/reprodução)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    f.linha(mx, 5.0, mx, y0)
    f.linha(mx, y1, mx, fm.altura - 5.0)
    f.linha(5.0, my, x0, my)
    f.linha(x1, my, fm.largura - 5.0, my)


def legenda(f: Folha, fm: Formato) -> None:
    _, uy0, ux1, _ = area_util(fm)
    x0 = ux1 - LEG_L
    y0 = uy0

    def X(v: float) -> float:
        return x0 + v

    def Y(v: float) -> float:
        return y0 + v

    f.retangulo(x0, y0, LEG_L, LEG_H)

    # --- grade: cada horizontal só atravessa a coluna a que pertence ----
    f.linha(X(0), Y(52.0), X(LEG_L), Y(52.0))
    for y in (22.0, 32.0, 42.0):    # coluna esquerda (revisão/formato/escala/vistos)
        f.linha(X(0), Y(y), X(70.0), Y(y))
    for y in (8.0, 22.0):           # coluna direita (título/nº/rodapé)
        f.linha(X(70.0), Y(y), X(LEG_L), Y(y))

    # --- faixa superior: material / tratamento / peso -------------------
    for x in (70.0, 115.0, 150.0):
        f.linha(X(x), Y(52.0), X(x), Y(62.0))

    f.rotulo_campo("NOTA:", X(0), Y(62.0))
    f.nota('Tol. geral: $PRP:"TOLERANCIA GERAL"', X(3.0), Y(53.5), altura=2.6)
    simbolo_projecao(f, X(58.0), Y(56.5))
    f.rotulo_campo("MATERIAL:", X(70.0), Y(62.0))
    f.nota('$PRPSHEET:{MATERIAL}', X(92.5), Y(53.2), altura=2.8, just="center", negrito=True)
    f.rotulo_campo("TRATAM.:", X(115.0), Y(62.0))
    f.nota('$PRP:"TRATAMENTO"', X(132.5), Y(53.2), altura=2.8, just="center")
    f.rotulo_campo("PESO (kg):", X(150.0), Y(62.0))
    f.nota('$PRPSHEET:{SW-Mass}', X(165.0), Y(53.2), altura=2.8, just="center", negrito=True)

    # --- coluna esquerda: formato / escala / desenhado / aprovado -------
    f.linha(X(70.0), Y(0.0), X(70.0), Y(52.0))
    # três colunas: [o quê] [quem] [quando] — a última é larga porque as datas
    # automáticas do SolidWorks vêm com hora ("26/08/2026 20:14:46")
    for x in (20.0, 42.0):
        f.linha(X(x), Y(32.0), X(x), Y(52.0))

    f.rotulo_campo("FORMATO", X(0), Y(52.0))
    f.nota(fm.rotulo, X(10.0), Y(43.5), altura=2.8, just="center", negrito=True)
    f.rotulo_campo("ESCALA", X(0), Y(42.0))
    f.nota('$PRP:"SW-Sheet Scale"', X(10.0), Y(33.5), altura=2.8, just="center", negrito=True)

    f.rotulo_campo("DESENHADO", X(20.0), Y(52.0))
    f.nota('$PRP:"DESENHADO"', X(31.0), Y(43.5), altura=2.8, just="center")
    # data em que o desenho nasceu — fixa, não é a data de hoje
    f.rotulo_campo("DATA", X(42.0), Y(52.0))
    # 2,1 mm: a data automática vem com hora e precisa caber nos 26 mm da célula
    f.nota('$PRP:"SW-Created Date"', X(56.0), Y(43.5), altura=2.0, just="center")

    f.rotulo_campo("APROVADO", X(20.0), Y(42.0))
    f.nota('$PRP:"APROVADO"', X(31.0), Y(33.5), altura=2.8, just="center")
    f.rotulo_campo("DATA", X(42.0), Y(42.0))
    f.nota('$PRP:"DATA APROVACAO"', X(56.0), Y(33.5), altura=2.4, just="center")

    # --- revisão corrente: quem fez e quando ----------------------------
    for x in (20.0, 42.0):
        f.linha(X(x), Y(22.0), X(x), Y(32.0))
    f.rotulo_campo("REV.", X(0), Y(32.0))
    f.nota('$PRP:"Revisão"', X(10.0), Y(23.5), altura=2.8, just="center", negrito=True)
    f.rotulo_campo("NOME", X(20.0), Y(32.0))
    f.nota('$PRP:"NOME REVISAO"', X(31.0), Y(23.5), altura=2.8, just="center")
    # última gravação do arquivo = quando a revisão foi feita
    f.rotulo_campo("DATA REV.", X(42.0), Y(32.0))
    f.nota('$PRP:"SW-Last Saved Date"', X(56.0), Y(23.5), altura=2.0, just="center")

    # --- título ---------------------------------------------------------
    f.rotulo_campo("TÍTULO:", X(70.0), Y(52.0))
    f.nota('$PRPSHEET:{DESCRICAO}', X(125.0), Y(33.0), altura=H_TITULO, just="center", negrito=True)

    # --- OS / nº do desenho / revisão -----------------------------------
    for x in (110.0, 160.0):
        f.linha(X(x), Y(8.0), X(x), Y(22.0))
    f.rotulo_campo("Nº OS:", X(70.0), Y(22.0))
    f.nota('$PRP:"OS"', X(90.0), Y(10.0), altura=H_VALOR, just="center")
    f.rotulo_campo("Nº DESENHO:", X(110.0), Y(22.0))
    f.nota('$PRP:"SW-File Name"', X(135.0), Y(10.0), altura=H_DESTAQUE, just="center", negrito=True)
    f.rotulo_campo("REV.:", X(160.0), Y(22.0))
    # "Revisão" é a propriedade que o SolidWorks usa como revisão corrente da
    # folha (swDrawingCustomPropertyUsedAsRevision) — a tabela escreve nela
    f.nota('$PRP:"Revisão"', X(170.0), Y(10.0), altura=H_DESTAQUE, just="center", negrito=True)

    # --- rodapé: arquivo CAD e paginação --------------------------------
    f.linha(X(140.0), Y(0.0), X(140.0), Y(8.0))
    f.rotulo_campo("ARQUIVO CAD:", X(70.0), Y(8.0))
    f.nota('$PRP:"SW-File Name"', X(120.0), Y(1.2), altura=2.8, just="center")
    f.nota(
        'FOLHA $PRP:"SW-Current Sheet" DE $PRP:"SW-Total Sheets"',
        X(160.0), Y(2.5), altura=2.6, just="center",
    )

    # --- logo -----------------------------------------------------------
    if os.path.exists(LOGO) and not SEM_LOGO:
        # a imagem entra pelo caminho normal; o SW cria junto uma linha de
        # centro que precisa sair depois, senão ela aparece no desenho
        f.sm.AddToDB = False
        antes = f.ids_dos_segmentos()
        raw = f.sm.InsertSketchPicture(LOGO)
        f.sm.AddToDB = True
        pic = cast_to(raw, "ISketchPicture") if raw is not None else None
        if pic is not None:
            larg, alt = 58.0, 17.0   # o logo horizontal é ~3,4:1; cabe nos 22 mm
            pic.SetSize(m(larg), m(alt), False)
            pic.SetOrigin(m(X(35.0) - larg / 2), m(Y(11.0) - alt / 2))
        f.remover_segmentos_novos(antes)
    else:
        f.nota("GROMAR", X(35.0), Y(13.0), altura=7.0, just="center", negrito=True)




# ------------------------------------------------------------- orquestração


def gerar(app, fm: Formato, dest: str, fechar: bool = True) -> str:
    sw = swconst()
    template = app.GetUserPreferenceStringValue(sw.swDefaultTemplateDrawing)
    if not template or not os.path.exists(template):
        raise RuntimeError(f"template de desenho padrão não encontrado: {template!r}")

    model = app.NewDocument(template, sw.swDwgPapersUserDefined, m(fm.largura), m(fm.altura))
    if model is None:
        raise RuntimeError("NewDocument devolveu None")
    model = cast_to(model, "IModelDoc2")
    draw = cast_to(model, "IDrawingDoc")

    # folha do tamanho pedido e SEM formato: começamos de uma folha limpa
    draw.SetupSheet5(
        "Folha1", sw.swDwgPapersUserDefined, sw.swDwgTemplateNone,
        1.0, 1.0, True, "", m(fm.largura), m(fm.altura), "Padrão", True,
    )

    draw.EditTemplate()
    model.ClearSelection2(True)

    try:
        f = Folha(model, sw)
        moldura(f, fm)
        legenda(f, fm)
        f.encerrar()
    except Exception:
        # não deixa desenho meio-feito acumulando na sessão do usuário
        app.CloseDoc(model.GetTitle)
        raise

    draw.EditSheet()
    model.ViewZoomtofit2()
    model.ClearSelection2(True)

    # ISheet::SaveFormat grava o .slddrt (SaveAs2 com essa extensão não grava nada)
    caminho = os.path.join(dest, f"{fm.nome}.slddrt")
    sheet = cast_to(draw.GetCurrentSheet(), "ISheet")
    sheet.SaveFormat(caminho)
    if not os.path.exists(caminho):
        raise RuntimeError(f"não foi possível gravar {caminho}")
    if fechar:
        app.CloseDoc(model.GetTitle)  # o título acompanha o nome salvo
    return caminho


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append", choices=sorted(FORMATOS), help="gera só estes formatos")
    p.add_argument("--dest", required=True, help="pasta de destino dos .slddrt")
    p.add_argument("--manter-aberto", action="store_true", help="não fecha o desenho no fim (para inspeção)")
    p.add_argument("--sem-logo", action="store_true", help="gera sem a imagem do logo (diagnóstico)")
    args = p.parse_args()

    global SEM_LOGO
    SEM_LOGO = args.sem_logo

    alvos = args.only or list(FORMATOS)
    os.makedirs(args.dest, exist_ok=True)

    session = SwSession()
    try:
        for chave in alvos:
            fm = FORMATOS[chave]
            caminho = session.run(
                lambda app, fm=fm: gerar(app, fm, args.dest, fechar=not args.manter_aberto)
            )
            print(f"ok  {chave:4s} -> {caminho}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
