"""Gera os templates de desenho (.drwdot) que já nascem com o formato Gromar.

Cada template traz a folha no tamanho certo, o .slddrt correspondente aplicado,
unidades em mm e as propriedades da legenda já criadas (vazias) para o desenhista
só preencher. Opcionalmente passa a ser o template padrão do SolidWorks.

Uso:
    python tools/gerar_templates_gromar.py --padrao a3
    python tools/gerar_templates_gromar.py --only a3 --only a4 --sem-definir-padrao
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from gerar_formatos_gromar import FORMATOS, Formato, m  # noqa: E402
from swmcp.com.session import SwSession, cast_to, swconst  # noqa: E402

SHEETFORMATS = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2023\lang\portuguese-brazilian\sheetformat\Gromar"
TEMPLATES = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2023\templates"

# propriedades que a legenda lê do próprio desenho, com o valor que já vem
# preenchido no template (vazio = o desenhista digita)
PROPRIEDADES = {
    "DESENHADO": "Rafael",   # desenhista fixo desta máquina
    "APROVADO": "",
    "DATA APROVACAO": "",
    "OS": "",
    "Revisão": "",           # nome fixado pelo SolidWorks para a revisão corrente
    "NOME REVISAO": "Rafael",
    "TRATAMENTO": "",
    "TOLERANCIA GERAL": "",
}


def nome_template(fm: Formato) -> str:
    return f"Desenho {fm.nome.replace(' - gromar', '')} - Gromar"


def gerar(app, chave: str, fm: Formato, base_template: str) -> str:
    sw = swconst()
    model = app.NewDocument(base_template, sw.swDwgPapersUserDefined, m(fm.largura), m(fm.altura))
    if model is None:
        raise RuntimeError(f"NewDocument falhou para {chave}")
    model = cast_to(model, "IModelDoc2")
    draw = cast_to(model, "IDrawingDoc")

    formato = os.path.join(SHEETFORMATS, f"{fm.nome}.slddrt")
    if not os.path.exists(formato):
        raise RuntimeError(f"formato não encontrado: {formato} (rode gerar_formatos_gromar.py antes)")

    ok = draw.SetupSheet5(
        "Folha1", sw.swDwgPapersUserDefined, sw.swDwgTemplateCustom,
        1.0, 1.0, True,  # escala 1:1, primeiro diedro
        formato, m(fm.largura), m(fm.altura), "Padrão", True,
    )
    if not ok:
        raise RuntimeError(f"não foi possível aplicar {formato}")

    ext = model.Extension
    ext.SetUserPreferenceInteger(sw.swUnitSystem, 0, sw.swUnitSystem_MMGS)
    ext.SetUserPreferenceInteger(sw.swUnitsLinear, 0, sw.swMM)
    ext.SetUserPreferenceInteger(sw.swUnitsLinearDecimalPlaces, 0, 2)
    ext.SetUserPreferenceInteger(sw.swUnitsAngularDecimalPlaces, 0, 2)

    # as propriedades vêm antes da tabela: a coluna de revisão é ligada a
    # REVISAO, e o vínculo não pega se a propriedade ainda não existir
    props = ext.CustomPropertyManager("")
    for nome, valor in PROPRIEDADES.items():
        props.Add3(nome, sw.swCustomInfoText, valor, sw.swCustomPropertyDeleteAndAdd)
    # herança de gerações antigas da legenda: some com o campo órfão
    if "REVISAO" in (props.GetNames() or ()):
        props.Delete2("REVISAO")


    model.ForceRebuild3(False)
    caminho = os.path.join(TEMPLATES, f"{nome_template(fm)}.drwdot")
    antes = os.path.getmtime(caminho) if os.path.exists(caminho) else None
    model.SaveAs2(caminho, 0, True, False)  # o retorno não é confiável aqui
    if not os.path.exists(caminho) or os.path.getmtime(caminho) == antes:
        raise RuntimeError(f"não foi possível gravar {caminho}")
    app.CloseDoc(model.GetTitle())
    return caminho


def definir_padrao(app, caminho: str) -> str:
    sw = swconst()
    anterior = app.GetUserPreferenceStringValue(sw.swDefaultTemplateDrawing)
    app.SetUserPreferenceStringValue(sw.swDefaultTemplateDrawing, caminho)
    return anterior


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", action="append", choices=sorted(FORMATOS), help="gera só estes")
    p.add_argument("--padrao", choices=sorted(FORMATOS), default="a3",
                   help="qual formato vira o template padrão do SolidWorks (default: a3)")
    p.add_argument("--sem-definir-padrao", action="store_true",
                   help="só gera os templates, sem mexer na preferência do SolidWorks")
    args = p.parse_args()

    alvos = args.only or list(FORMATOS)
    session = SwSession()
    try:
        # sempre partir do template nativo: usar o próprio Gromar como base
        # acumularia formato e tabelas antigas a cada regeração
        base = os.path.join(TEMPLATES, "Desenho.drwdot")
        if not os.path.exists(base):
            raise RuntimeError(f"template base do SolidWorks não encontrado: {base}")
        print(f"template base: {base}")
        gerados = {}
        for chave in alvos:
            fm = FORMATOS[chave]
            caminho = session.run(lambda app, c=chave, f=fm: gerar(app, c, f, base))
            gerados[chave] = caminho
            print(f"ok  {chave:4s} -> {caminho}")

        if not args.sem_definir_padrao:
            alvo = gerados.get(args.padrao)
            if alvo is None:
                print(f"aviso: {args.padrao} não foi gerado nesta execução; padrão inalterado")
            else:
                anterior = session.run(lambda app: definir_padrao(app, alvo))
                print(f"padrão: {anterior}\n     -> {alvo}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
