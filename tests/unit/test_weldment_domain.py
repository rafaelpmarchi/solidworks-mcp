"""Weldment (domínio puro): catálogo de perfis e normalização da lista de corte."""

from swmcp.domain import weldment as w


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


def test_catalogo_aceita_layout_configurado_e_legado(tmp_path):
    _touch(tmp_path / "iso" / "square tube.sldlfp")
    _touch(tmp_path / "iso" / "pipe.sldlfp")
    _touch(tmp_path / "Gromar" / "tubo retangular" / "40 x 20 x 1.5.sldlfp")
    _touch(tmp_path / "iso" / "leiame.txt")  # ignorado

    cat = w.scan_profile_folders([str(tmp_path), str(tmp_path)])  # pasta repetida não duplica

    assert [(p.standard, p.kind) for p in cat] == [
        ("Gromar", "tubo retangular"),
        ("iso", "pipe"),
        ("iso", "square tube"),
    ]
    legado = cat[0]
    assert legado.sizes == ("40 x 20 x 1.5",)
    assert cat[1].sizes == ()  # tamanhos configurados vêm do COM


def test_catalogo_ignora_pasta_inexistente(tmp_path):
    assert w.scan_profile_folders([str(tmp_path / "nada")]) == []


def test_find_profile_sem_diferenciar_caixa(tmp_path):
    _touch(tmp_path / "iso" / "square tube.sldlfp")
    cat = w.scan_profile_folders([str(tmp_path)])
    assert w.find_profile(cat, "ISO", "Square Tube") is cat[0]
    assert w.find_profile(cat, "iso", "pipe") is None


def test_chave_canonica_vem_da_formula_ou_do_nome_localizado():
    assert w.canonical_property_key("COMPRIMENTO", '"LENGTH@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"') == "LENGTH"
    assert w.canonical_property_key("ÂNGULO1", '"ANGLE1@@@X<1>@P.SLDPRT"') == "ANGLE1"
    assert w.canonical_property_key("TOTAL LENGTH", '"TOTAL LENGTH@@@X<1>@P.SLDPRT"') == "TOTAL LENGTH"
    # Descrição: fórmula é texto livre com "Out_dia@…", não segue @@@
    assert w.canonical_property_key("Descrição", 'PIPE "Out_dia@<iso><pipe>(1)@P.SLDPRT" X 2.3') == "DESCRIPTION"
    assert w.canonical_property_key("Minha prop", "abc") == "MINHA PROP"


def test_parse_number():
    assert w.parse_number("300") == 300.0
    assert w.parse_number("0°") == 0.0
    assert w.parse_number("12,5") == 12.5
    assert w.parse_number("-") is None
    assert w.parse_number("") is None
    assert w.parse_number("Material <não especificado>") is None


def test_normaliza_item_da_lista_de_corte_real():
    raw = {
        "COMPRIMENTO": ('"LENGTH@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "200"),
        "ÂNGULO1": ('"ANGLE1@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "45°"),
        "ÂNGULO2": ('"ANGLE2@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "-"),
        "Descrição": ('PIPE "Out_dia@<iso><pipe><21.3 x 2.3>(1)@Peça1.SLDPRT" X 2.3', "PIPE 21,30 X 2.3"),
        "MATERIAL": ('"SW-Material@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "AISI 304"),
        "QUANTITY": ('"QUANTITY@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "2"),
        "TOTAL LENGTH": ('"TOTAL LENGTH@@@PIPE 21,30 X 2.3<1>@Peça1.SLDPRT"', "400"),
    }
    item = w.normalize_cut_list_item("PIPE 21,30 X 2.3<1>", raw, bodies=2, body_names=["a", "b"])
    assert item["description"] == "PIPE 21,30 X 2.3"
    assert item["quantity"] == 2
    assert item["length"] == 200.0
    assert item["total_length"] == 400.0
    assert item["angle1_deg"] == 45.0
    assert item["angle2_deg"] is None
    assert item["material"] == "AISI 304"
    assert item["bodies"] == 2 and item["body_names"] == ["a", "b"]
    assert item["properties"]["MATERIAL"] == "AISI 304"
    assert item["properties"]["LENGTH"] == "200"


def test_quantidade_cai_no_numero_de_corpos_sem_propriedade():
    item = w.normalize_cut_list_item("X<1>", {}, bodies=3)
    assert item["quantity"] == 3
    assert item["length"] is None


def test_combina_contornos_pega_o_mais_recuado():
    externo = [(a, 0.0) for a in range(-180, 180, 30)]          # reto em s=0
    interno = [(a, 5.0 if a > 0 else -5.0) for a in range(-180, 180, 30)]
    comb = w.combine_outlines([externo, interno], toward=+1, step_deg=90)
    por_ang = dict(comb)
    assert por_ang[90.0] == 5.0      # interno mais recuado (+s) manda
    assert por_ang[-90.0] == 0.0     # externo manda
    comb_neg = dict(w.combine_outlines([externo, interno], toward=-1, step_deg=90))
    assert comb_neg[90.0] == 0.0 and comb_neg[-90.0] == -5.0


def test_lacuna_angular():
    assert w.angular_gap_deg([(a, 0.0) for a in range(-180, 180, 10)]) == 10.0
    assert w.angular_gap_deg([(0.0, 0.0), (90.0, 0.0)]) == 270.0


def test_combine_exige_contorno_e_sentido():
    import pytest
    with pytest.raises(ValueError):
        w.combine_outlines([], 1)
    with pytest.raises(ValueError):
        w.combine_outlines([[(0.0, 0.0)]], 0)


def test_geometria_de_perfil_nomes_e_validacao():
    from swmcp.com.wrappers.weldment import _profile_geometry
    desc, size, _ = _profile_geometry("round_tube", 50.8, 2.0, 0, 0, None)
    assert desc == "Tubo Redondo 50.8 x 2mm" and size == "50.8 x 2mm"
    desc, size, _ = _profile_geometry("rect_tube", 0, 1.2, 40, 30, 4.5)
    assert desc == "Metalon 30x40x1.2mm" and size == "30 x 40 x 1.2mm"
    desc, size, _ = _profile_geometry("square_tube", 0, 1.5, 20, 0, None)
    assert size == "20 x 20 x 1.5mm"
    import pytest
    with pytest.raises(ValueError):
        _profile_geometry("round_tube", 10, 6, 0, 0, None)   # parede maior que o raio
    with pytest.raises(ValueError):
        _profile_geometry("hexagono", 1, 1, 1, 1, None)
