"""Leitura do modelo 3D referenciado (RF-04). Executa no thread STA."""

from __future__ import annotations

import logging
from typing import Any

from swmcp.com import units
from swmcp.com.invoke import com_call, com_get
from swmcp.com.session import cast_to
from swmcp.com.wrappers.drawing import read_custom_properties
from swmcp.domain.model import BoundingBox, ModelProperties

log = logging.getLogger(__name__)

MAX_FEATURES = 200


def read_model(doc: Any, path: str) -> ModelProperties:
    """Monta ModelProperties de um documento (peça/montagem) JÁ aberto."""
    model = cast_to(doc, "IModelDoc2")
    doc_type = com_call(model, "GetType")

    configurations = list(com_call(model, "GetConfigurationNames") or ())
    active_config = None
    cfg = com_get(model, "ConfigurationManager")
    if cfg is not None:
        active = com_get(cast_to(cfg, "IConfigurationManager"), "ActiveConfiguration")
        if active is not None:
            active_config = com_get(cast_to(active, "IConfiguration"), "Name")

    material = None
    if doc_type == 1:  # peça
        part = cast_to(doc, "IPartDoc")
        raw = com_call(part, "GetMaterialPropertyName2", active_config or "", "")
        # early binding: retorna (nome, database) — nome vazio = sem material
        if isinstance(raw, tuple):
            material = raw[0] or None
        else:
            material = raw or None

    mass_kg = None
    bbox = None
    try:
        ext = com_get(model, "Extension")
        mp = com_call(ext, "CreateMassProperty")
        if mp is not None:
            mp = cast_to(mp, "IMassProperty")
            mass_kg = round(com_get(mp, "Mass"), 6)
    except Exception as exc:  # noqa: BLE001 — massa é opcional; logado, não engolido
        log.warning("massa indisponível para %s: %s", path, exc)

    try:
        if doc_type == 1:
            box = com_call(cast_to(doc, "IPartDoc"), "GetPartBox", True)
            if box and len(box) >= 6:
                bbox = BoundingBox(
                    x_mm=units.round_mm(abs(box[3] - box[0])),
                    y_mm=units.round_mm(abs(box[4] - box[1])),
                    z_mm=units.round_mm(abs(box[5] - box[2])),
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("bounding box indisponível para %s: %s", path, exc)

    return ModelProperties(
        path=path,
        title=com_call(model, "GetTitle"),
        configuration=active_config,
        material=material,
        mass_kg=mass_kg,
        bounding_box=bbox,
        custom_properties=read_custom_properties(model, ""),
        config_properties=read_custom_properties(model, active_config) if active_config else {},
        configurations=configurations,
        features=_read_features(model),
    )


def _read_features(model: Any) -> list[str]:
    features: list[str] = []
    raw = com_call(model, "FirstFeature")
    while raw is not None and len(features) < MAX_FEATURES:
        feat = cast_to(raw, "IFeature")
        features.append(f"{com_call(feat, 'Name')} ({com_call(feat, 'GetTypeName2')})")
        raw = com_call(feat, "GetNextFeature")
    return features
