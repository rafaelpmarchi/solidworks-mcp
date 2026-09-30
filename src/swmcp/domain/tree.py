"""Organização da árvore de features em pastas (puro, sem COM).

Pasta na árvore do SolidWorks só agrupa features CONTÍGUAS. Para montar as
pastas por face (padrão Gromar: "TOPO", "Face +Y (KZ)"...), primeiro as
features são reordenadas na sequência dos grupos e só então viram pastas. E
IModelDocExtension::ReorderFeature devolve False mesmo quando move (medido no
SW2023) — a única verdade é a ordem lida da árvore depois.
"""

from __future__ import annotations

from collections.abc import Sequence


def desired_sequence(groups: Sequence[tuple[str, Sequence[str]]]) -> list[str]:
    """As features na ordem em que devem ficar, grupo após grupo."""
    vistos: set[str] = set()
    saida: list[str] = []
    for nome_grupo, features in groups:
        for f in features:
            if f in vistos:
                raise ValueError(f"a feature {f!r} está em mais de um grupo (repetida em {nome_grupo!r})")
            vistos.add(f)
            saida.append(f)
    return saida


def order_mismatches(tree_order: Sequence[str], wanted: Sequence[str]) -> list[tuple[str, str]]:
    """Onde a ordem real das features pedidas diverge da sequência pedida.

    Só as features pedidas entram na comparação: os esboços absorvidos
    aparecem soltos na varredura da árvore e não atrapalham a pasta.
    """
    faltando = [w for w in wanted if w not in tree_order]
    if faltando:
        return [(w, "<não está na árvore>") for w in faltando]
    alvo = set(wanted)
    real = [n for n in tree_order if n in alvo]
    return [(w, r) for w, r in zip(wanted, real) if w != r]
