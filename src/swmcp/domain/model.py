"""DTOs de leitura do modelo 3D (RF-04). Unidades: mm e kg."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x_mm: float
    y_mm: float
    z_mm: float


class ModelProperties(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    title: str
    configuration: str | None = None
    material: str | None = None
    mass_kg: float | None = None
    bounding_box: BoundingBox | None = None
    custom_properties: dict[str, str] = {}  # nível do documento
    config_properties: dict[str, str] = {}  # da configuração ativa/indicada
    configurations: list[str] = []
    features: list[str] = []
