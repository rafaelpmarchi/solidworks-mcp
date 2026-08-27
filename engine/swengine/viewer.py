"""Suporte ao visualizador 3D do painel.

pack: malha decimada num binário compacto (little-endian):
  uint32 magic 'SWM1' (0x314D5753) | uint32 nv | uint32 nf
  float32 verts[nv*3] | uint32 faces[nf*3] | int32 labels[nv] (-1 sem rótulo)
O viewer trabalha na malha DECIMADA; savemask leva a seleção de volta à malha
cheia por vizinho mais próximo.
"""

from __future__ import annotations

import struct

import numpy as np
import trimesh
from scipy.spatial import cKDTree

MAGIC = 0x314D5753


def pack(mesh: trimesh.Trimesh, out_path: str, target_faces: int = 80000,
         labels: np.ndarray | None = None) -> dict:
    from . import mesh_io

    small = mesh_io.decimate(mesh, target_faces)
    lab = np.full(len(small.vertices), -1, dtype=np.int32)
    if labels is not None:
        tree = cKDTree(mesh.vertices)
        _, idx = tree.query(small.vertices, workers=-1)
        lab = labels[idx].astype(np.int32)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<III", MAGIC, len(small.vertices), len(small.faces)))
        f.write(small.vertices.astype("<f4").tobytes())
        f.write(small.faces.astype("<u4").tobytes())
        f.write(lab.tobytes())
    return {"bin": out_path, "vertices": int(len(small.vertices)),
            "faces": int(len(small.faces))}


def unpack_vertices(bin_path: str) -> np.ndarray:
    with open(bin_path, "rb") as f:
        magic, nv, _nf = struct.unpack("<III", f.read(12))
        if magic != MAGIC:
            raise ValueError("binário do viewer inválido")
        return np.frombuffer(f.read(nv * 12), dtype="<f4").reshape(-1, 3)


def save_mask(mesh: trimesh.Trimesh, viewer_bin: str, selected_idx: list,
              out_path: str) -> dict:
    """Seleção feita na malha do viewer -> máscara na malha CHEIA.

    A dilatação usa o espaçamento típico da malha do viewer, para a máscara
    cobrir os vértices da malha cheia que ficam ENTRE os selecionados."""
    vv = unpack_vertices(viewer_bin)
    idx = np.asarray(selected_idx, dtype=np.int64)
    if len(idx) == 0:
        raise ValueError("seleção vazia")
    sel = vv[idx]
    tree = cKDTree(sel)
    # espaçamento típico entre vizinhos selecionados
    d2 = tree.query(sel, k=min(2, len(sel)), workers=-1)[0]
    spacing = float(np.median(d2[:, -1])) if len(sel) > 1 else 1.0
    raio = max(1.0, spacing * 1.5)
    dist, _ = tree.query(mesh.vertices, workers=-1)
    mask = dist <= raio
    np.save(out_path, mask)
    return {"mask": out_path, "vertices_na_mascara": int(mask.sum()),
            "fracao": round(float(mask.mean()), 4),
            "raio_dilatacao_mm": round(raio, 3)}
