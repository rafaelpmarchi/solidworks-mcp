"""Peça de revolução escaneada: eixo, perfil (r, z) e furos em padrão.

É o que se fazia à mão na engenharia reversa de uma aranha de disco de freio
(02/10/2026): o PCA deixou o eixo 3,6 mm fora do furo, o cilindro restrito
pegou 2,8 % de inliers, e o perfil e os furos saíram de scripts numpy.

- fit_axis: eixo pela geometria de linhas (Pottmann & Randrup). Numa
  superfície de revolução toda reta normal corta o eixo, então o momento
  (p - c)·(n × a) é zero para todo ponto. Mínimos quadrados com pesos
  robustos (IRLS) — furos fora do eixo, orelhas e ruído viram outliers.
- revolve_profile: (r, z) de pontos densos da superfície, guardando só as
  células (r, z) vistas em boa parte da volta (cobertura angular); onde duas
  superfícies se alternam na volta (orelha × aba), fica a de maior cobertura.
  A curva é ordenada pela árvore geradora mínima, simplificada por
  Douglas-Peucker, as retas reajustadas e os cantos viram vértices vivos com
  o raio de concordância estimado.
- detect_holes: projeção ao longo do eixo, ocupação em grade, regiões vazias
  fechadas; o Ø sai do ajuste de círculo nas PAREDES do furo (pontos de
  normal perpendicular ao eixo) — o raster sozinho erra ~0,4 mm. Agrupa por
  Ø e raio e acha o passo angular (12 posições a cada 30°, 5 ocupadas...).

Unidades: mm e graus. Eixo dado por ponto + direção; tudo é calculado no
referencial do eixo (r radial, z axial a partir do ponto do eixo).
"""

from __future__ import annotations

import numpy as np
import trimesh

from .region import region_vertex_mask


# ------------------------------------------------------------------ apoio

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def axis_frame(axis_dir) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(u, v, a): base ortonormal destra com a = eixo. u segue +X do modelo
    quando dá (para o ângulo 0° bater com o eixo X do SolidWorks)."""
    a = _unit(axis_dir)
    ref = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(ref - a * (ref @ a))
    v = np.cross(a, u)
    return u, v, a


def _face_subset(mesh: trimesh.Trimesh, region: dict | None,
                 max_faces: int, seed: int = 0) -> np.ndarray:
    """Índices de faces dentro da região (todos os vértices dentro), sorteados
    até max_faces."""
    vmask = region_vertex_mask(mesh, region)
    fmask = vmask[mesh.faces].all(axis=1)
    idx = np.flatnonzero(fmask)
    if len(idx) > max_faces:
        idx = np.random.default_rng(seed).choice(idx, max_faces, replace=False)
    return idx


def _pca_normals(pts: np.ndarray, normals: np.ndarray, k: int = 40,
                 chunk: int = 50000) -> np.ndarray:
    """Normal por PCA local dos k vizinhos, orientada como a normal da face.

    A normal de UMA face de scan erra alguns graus — a 70 mm do eixo isso
    desloca a reta normal 2-3 mm e o eixo sai torto. A média local cai para
    décimos de grau."""
    from scipy.spatial import cKDTree

    tree = cKDTree(pts)
    out = np.empty_like(normals)
    for s in range(0, len(pts), chunk):
        q = pts[s:s + chunk]
        _, idx = tree.query(q, min(k, len(pts)))
        nb = pts[idx] - pts[idx].mean(1, keepdims=True)
        cov = np.einsum("nki,nkj->nij", nb, nb)
        _, vec = np.linalg.eigh(cov)
        nrm = vec[:, :, 0]
        flip = (nrm * normals[s:s + chunk]).sum(1) < 0
        nrm[flip] *= -1
        out[s:s + chunk] = nrm
    return out


def _surface_samples(mesh: trimesh.Trimesh, density_per_mm2: float,
                     max_points: int, region: dict | None = None,
                     seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Pontos uniformes na área (com a normal da face de cada um)."""
    m = mesh
    if region:
        fidx = _face_subset(mesh, region, len(mesh.faces))
        m = mesh.submesh([fidx], append=True)
    n = int(min(max_points, max(20000, m.area * density_per_mm2)))
    pts, fid = trimesh.sample.sample_surface(m, n, seed=seed)
    return np.asarray(pts), np.asarray(m.face_normals[fid])


# ------------------------------------------------------------------- eixo

def fit_axis(mesh: trimesh.Trimesh, region: dict | None = None,
             axis_hint: list | None = None, max_points: int = 60000,
             inlier_mm: float = 0.3, iterations: int = 15) -> dict:
    """Eixo de revolução da malha (ponto + direção), robusto a furos e orelhas.

    Amostra pontos uniformes na área, com normal por PCA local. Plücker do
    eixo (a, ā = c × a); resíduo do ponto = (p × n)·a + n·ā = (p - c)·(n × a),
    que é a distância entre a reta normal e o eixo vezes |n × a|. Minimiza
    Σ w r² com |a| = 1: ā sai fechado, a é o menor autovetor do complemento
    de Schur. Faces planas perpendiculares ao eixo (n ∥ a) dão resíduo zero
    para qualquer c — prendem só a direção, como devem.
    """
    pts, nrm = _surface_samples(mesh, 8.0, 4 * max_points, region, seed=1)
    if len(pts) < 50:
        raise ValueError("região com menos de 50 pontos para achar o eixo")
    nrm = _pca_normals(pts, nrm)
    sel = np.random.default_rng(2).choice(len(pts), min(max_points, len(pts)), replace=False)
    p, n = pts[sel], nrm[sel]
    area = np.ones(len(p))
    idx = sel
    centroid = (p * area[:, None]).sum(0) / area.sum()
    p = p - centroid  # condiciona o sistema (coordenadas de scan ficam longe da origem)
    m = np.cross(p, n)
    rows = np.hstack([m, n])

    w = area / area.mean()
    a = abar = None
    dist = None
    for _ in range(max(1, iterations)):
        M = (rows * w[:, None]).T @ rows
        A, B, C = M[:3, :3], M[:3, 3:], M[3:, 3:]
        Cinv = np.linalg.pinv(C)
        S = A - B @ Cinv @ B.T
        vals, vecs = np.linalg.eigh((S + S.T) / 2)
        a = vecs[:, 0]
        abar = -Cinv @ B.T @ a
        res = rows @ np.concatenate([a, abar])
        sin = np.linalg.norm(np.cross(n, a), axis=1)
        dist = np.abs(res) / np.maximum(sin, 1e-3)
        # IRLS (Cauchy): escala pela mediana das faces que de fato prendem a
        # posição do eixo (normal inclinada em relação a ele)
        informativas = sin > 0.3
        s = float(np.median(dist[informativas])) if informativas.any() else 1.0
        s = max(s, 0.5 * inlier_mm)
        w = (area / area.mean()) / (1.0 + (dist / (2.0 * s)) ** 2)

    a = _unit(a)
    hint = np.asarray(axis_hint, float) if axis_hint is not None else None
    if hint is None:
        # sem dica: aponta o eixo para o lado de onde mais área "olha"
        hint = (n * area[:, None]).sum(0)
        if np.linalg.norm(hint) < 1e-9:
            hint = np.array([0, 0, 1.0])
    if a @ hint < 0:
        a, abar = -a, -abar
    c = np.cross(a, abar) + centroid  # ponto do eixo mais perto do centroide
    c = c + a * float((centroid - c) @ a)

    sin = np.linalg.norm(np.cross(n, a), axis=1)
    informativas = sin > 0.3
    inl = informativas & (dist <= inlier_mm)
    area_inf = float(area[informativas].sum()) or 1.0
    gap = float(vals[1] / vals[0]) if vals[0] > 1e-15 else float("inf")
    return {
        "axis_point": [round(float(x), 4) for x in c],
        "axis_dir": [round(float(x), 6) for x in a],
        "inlier_area_fraction": round(float(area[inl].sum()) / area_inf, 4),
        "rms_mm": round(float(np.sqrt(np.mean(dist[inl] ** 2))), 4) if inl.any() else None,
        "faces_used": int(len(idx)),
        "eigen_ratio": round(min(gap, 1e9), 2),
        "aviso": None if gap > 3 else
        "eixo mal determinado (peça quase esférica/plana ou pouca superfície "
        "de revolução) — confira, ou passe region com só as faces torneadas",
    }


def axis_alignment_matrix(axis_point, axis_dir, z_values: np.ndarray | None = None,
                          z_origin: str = "centroid") -> np.ndarray:
    """4x4 que leva o eixo para Z (+Z = axis_dir) e o ponto do eixo para a
    origem. Rotação mínima (a peça não gira em torno do eixo à toa).
    z_origin: 'centroid' (ponto do eixo), 'min' ou 'max' (das coordenadas
    axiais em z_values) — com 'min' a peça fica toda em Z ≥ 0."""
    a = _unit(axis_dir)
    z = np.array([0, 0, 1.0])
    v = np.cross(a, z)
    s, c = np.linalg.norm(v), float(a @ z)
    if s < 1e-12:
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        k = v / s
        K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        R = np.eye(3) + s * K + (1 - c) * K @ K
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ np.asarray(axis_point, float)
    if z_values is not None and z_origin in ("min", "max"):
        zs = np.asarray(z_values, float) - float(np.asarray(axis_point, float) @ a)
        T[2, 3] -= float(zs.min() if z_origin == "min" else zs.max())
    return T


# ------------------------------------------------------------------ perfil

def _rdp(pts: np.ndarray, tol: float) -> list[int]:
    """Douglas-Peucker iterativo; devolve índices mantidos."""
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        d = b - a
        L = np.linalg.norm(d)
        seg = pts[i + 1:j]
        if L < 1e-12:
            dist = np.linalg.norm(seg - a, axis=1)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return list(np.flatnonzero(keep))


def _fit_line(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    return c, vt[0]


def _intersect(c1, d1, c2, d2) -> np.ndarray | None:
    A = np.column_stack([d1, -d2])
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    t = np.linalg.solve(A, c2 - c1)
    return c1 + t[0] * d1


def _order_curve(pts: np.ndarray, k: int = 10) -> tuple[np.ndarray, bool]:
    """Ordena uma nuvem 2D fina como curva: MST + caminho mais longo."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra, minimum_spanning_tree
    from scipy.spatial import cKDTree

    n = len(pts)
    k = min(k, n - 1)
    d, j = cKDTree(pts).query(pts, k + 1)
    rows = np.repeat(np.arange(n), k)
    g = coo_matrix((d[:, 1:].ravel() + 1e-9, (rows, j[:, 1:].ravel())), shape=(n, n))
    g = g.maximum(g.T)
    # componentes desconexas (lacuna de scan) ligam pela menor distância
    from scipy.sparse.csgraph import connected_components
    ncomp, lab = connected_components(g, directed=False)
    if ncomp > 1:
        tree = cKDTree(pts)
        extra = []
        for comp in range(1, ncomp):
            a_idx = np.flatnonzero(lab == comp)
            b_idx = np.flatnonzero(lab != comp)
            dd, jj = cKDTree(pts[b_idx]).query(pts[a_idx])
            i = int(np.argmin(dd))
            extra.append((a_idx[i], b_idx[jj[i]], dd[i] + 1e-9))
        del tree
        er, ec, ev = zip(*extra)
        g = (g + coo_matrix((ev, (er, ec)), shape=(n, n))).tocsr()
        g = g.maximum(g.T)
    mst = minimum_spanning_tree(g)
    mst = mst.maximum(mst.T)
    d0 = dijkstra(mst, indices=0)
    s = int(np.argmax(np.where(np.isfinite(d0), d0, -1)))
    ds, pred = dijkstra(mst, indices=s, return_predecessors=True)
    t = int(np.argmax(np.where(np.isfinite(ds), ds, -1)))
    path = [t]
    while path[-1] != s:
        path.append(int(pred[path[-1]]))
    order = np.array(path[::-1])
    return pts[order], False


def _profile_points(r, z, theta, nrm_rz, cell_mm, arc_mm, min_coverage):
    """Células (r, z) com cobertura angular suficiente → pontos médios."""
    ir = np.floor(r / cell_mm).astype(np.int64)
    iz = np.floor(z / cell_mm).astype(np.int64)
    nsec = np.maximum(36, np.floor(2 * np.pi * np.maximum(r, cell_mm) / arc_mm)).astype(np.int64)
    sec = np.floor((theta % 360.0) / 360.0 * nsec).astype(np.int64)
    key = (ir << 32) ^ (iz & 0xFFFFFFFF)
    order = np.argsort(key, kind="stable")
    key_s = key[order]
    starts = np.flatnonzero(np.r_[True, key_s[1:] != key_s[:-1]])
    ends = np.r_[starts[1:], len(key_s)]
    cells = []
    for s0, e0 in zip(starts, ends):
        sel = order[s0:e0]
        cov = len(np.unique(sec[sel])) / float(np.median(nsec[sel]))
        cells.append((ir[sel[0]], iz[sel[0]], min(cov, 1.0),
                      float(r[sel].mean()), float(z[sel].mean()),
                      nrm_rz[sel].mean(0)))
    cells = [c for c in cells if c[2] >= min_coverage]
    if not cells:
        return None
    # superfícies que se alternam na volta (somam ~1 de cobertura) na mesma
    # coluna radial e desconexas em z: fica a de maior cobertura
    by_col: dict[int, list] = {}
    for c in cells:
        by_col.setdefault(c[0], []).append(c)
    # conflito = coluna com 2+ trechos desconexos em z que somam < 1,25 de
    # cobertura (se alternam na volta). A escolha é GLOBAL por nível de z
    # (todas as colunas da orelha escolhem o mesmo nível), não coluna a
    # coluna: decidir cada uma sozinha misturava topo da orelha e aba e a
    # curva fazia um desvio
    conflitos = {}
    for col, lst in by_col.items():
        lst.sort(key=lambda c: c[1])
        runs, run = [], [lst[0]]
        for c in lst[1:]:
            if c[1] - run[-1][1] <= 2:
                run.append(c)
            else:
                runs.append(run)
                run = [c]
        runs.append(run)
        if len(runs) < 2:
            continue
        covs = [float(np.mean([c[2] for c in rr])) for rr in runs]
        if sum(covs) < 1.25:
            conflitos[col] = (runs, covs)

    def nivel(rr):  # nível de z do trecho, em degraus de 1 mm
        return int(round(float(np.mean([c[4] for c in rr]))))

    peso: dict[int, float] = {}
    for runs, covs in conflitos.values():
        for rr, cv in zip(runs, covs):
            peso[nivel(rr)] = peso.get(nivel(rr), 0.0) + cv * len(rr)
    drop = set()
    descartados: dict[int, list[float]] = {}  # nível -> [r_min, r_max]
    for runs, covs in conflitos.values():
        fica = max(range(len(runs)), key=lambda i: (peso[nivel(runs[i])], covs[i]))
        for i, rr in enumerate(runs):
            if i != fica:
                drop.update((c[0], c[1]) for c in rr)
                faixa = descartados.setdefault(nivel(rr), [np.inf, -np.inf])
                faixa[0] = min(faixa[0], min(c[3] for c in rr))
                faixa[1] = max(faixa[1], max(c[3] for c in rr))
    cells = [c for c in cells if (c[0], c[1]) not in drop]
    pts = np.array([[c[3], c[4]] for c in cells])
    cov = np.array([c[2] for c in cells])
    nrm = np.array([c[5] for c in cells])
    return pts, cov, nrm, descartados


def _offset_closure(verts: np.ndarray, normals: np.ndarray, t: float) -> tuple[np.ndarray, str | None]:
    """Fecha o perfil aberto com a parede de espessura t para o lado oposto à
    normal do scan (retas deslocadas e cantos em esquadria)."""
    nseg = len(verts) - 1
    offs = []
    for i in range(nseg):
        p, q = verts[i], verts[i + 1]
        d = _unit(q - p)
        nl = np.array([-d[1], d[0]])
        if nl @ normals[i] > 0:  # nl aponta para fora do material
            nl = -nl
        offs.append((p + nl * t, d))

    def _inner(lines):
        pts = [lines[0][0] + lines[0][1] * float((verts[0] + 0 - lines[0][0]) @ lines[0][1])]
        for (c1, d1), (c2, d2) in zip(lines[:-1], lines[1:]):
            x = _intersect(c1, d1, c2, d2)
            pts.append(x if x is not None else c2)
        c, d = lines[-1]
        pts.append(c + d * float((verts[-1] - c) @ d))
        return np.array(pts)

    # trecho mais curto que a espessura inverte na parede interna: sai da
    # lista e os vizinhos se encontram direto (limpeza clássica de offset)
    removidos = 0
    while True:
        inner = _inner(offs)
        flip = next((i for i in range(len(offs))
                     if (inner[i + 1] - inner[i]) @ offs[i][1] <= 1e-9), None)
        if flip is None or len(offs) <= 2:
            break
        offs.pop(flip)
        removidos += 1
    aviso = None
    if removidos:
        aviso = (f"a parede interna de {t} mm engoliu {removidos} trecho(s) curto(s) "
                 "do perfil — é uma estimativa (scan de um lado só): confira a "
                 "espessura real antes de usar")
    closed = np.vstack([verts, inner[::-1], verts[:1]])
    return closed, aviso


def revolve_profile(mesh: trimesh.Trimesh, axis_point=(0, 0, 0), axis_dir=(0, 0, 1),
                    region: dict | None = None, cell_mm: float = 0.25,
                    arc_mm: float = 1.0, min_coverage: float = 0.4,
                    tol_mm: float = 0.1, density_per_mm2: float = 16.0,
                    max_points: int = 1_500_000,
                    thickness_mm: float | None = None) -> dict:
    """Perfil de revolução (r, z) da malha em torno do eixo dado.

    Devolve os vértices de uma polilinha de cantos vivos (o desenho do perfil
    no esboço) + o raio de concordância estimado em cada canto + a distância
    rms dos pontos à polilinha. thickness_mm fecha o perfil aberto (scan de
    um lado só) com uma parede de espessura constante — é uma ESTIMATIVA."""
    p0 = np.asarray(axis_point, float)
    u, v, a = axis_frame(axis_dir)
    pts, nrm = _surface_samples(mesh, density_per_mm2, max_points, region)
    d = pts - p0
    z = d @ a
    x, y = d @ u, d @ v
    r = np.hypot(x, y)
    theta = np.degrees(np.arctan2(y, x))
    radial = np.column_stack([x, y]) / np.maximum(r, 1e-9)[:, None]
    n_r = (nrm @ u) * radial[:, 0] + (nrm @ v) * radial[:, 1]
    n_z = nrm @ a
    got = _profile_points(r, z, theta, np.column_stack([n_r, n_z]),
                          cell_mm, arc_mm, min_coverage)
    if got is None or len(got[0]) < 10:
        raise ValueError("nenhuma superfície de revolução com cobertura angular "
                         f">= {min_coverage} — o eixo está certo? (mesh_align "
                         "mode='axis' antes) ou reduza min_coverage")
    cpts, cov, cnrm, descartados = got
    # afina a nuvem (média dos vizinhos) antes de ordenar
    from scipy.spatial import cKDTree
    tree = cKDTree(cpts)
    nb = tree.query_ball_point(cpts, 1.5 * cell_mm)
    thin = np.array([cpts[i].mean(0) for i in nb])
    curve, _ = _order_curve(thin)
    # ponta que sobe por uma parede até um nível DESCARTADO (a parede externa
    # da orelha quando ficou a aba) não é perfil: corta a ponta até sair dele
    for lado in (0, -1):
        p = curve[lado]
        for nv, (r0, r1) in descartados.items():
            if not (abs(p[1] - nv) < 1.0 and r0 - 1.0 <= p[0] <= r1 + 1.0):
                continue
            ordem = range(len(curve)) if lado == 0 else range(len(curve) - 1, -1, -1)
            r_parede = None
            corte = None
            for k in ordem:
                q = curve[k]
                if abs(q[1] - nv) < 1.0:
                    continue  # ainda no nível descartado
                if r_parede is None:
                    r_parede = q[0]
                if abs(q[0] - r_parede) > 0.5:
                    corte = k  # a parede acabou: daqui em diante é perfil
                    break
            if corte is not None:
                cortado = curve[:corte + 1] if lado == 0 else curve[corte:]
                comp = float(np.linalg.norm(np.diff(cortado, axis=0), axis=1).sum())
                if comp < 25.0:  # mais que isso não é só uma parede de orelha
                    curve = curve[corte:] if lado == 0 else curve[:corte + 1]
            break
    # normal de cada ponto da curva (para o lado da espessura)
    _, near = cKDTree(cpts).query(curve)
    cnorm = cnrm[near]

    keep = _rdp(curve, max(tol_mm, cell_mm))
    # reajusta cada trecho por mínimos quadrados (sem as pontas, onde mora o
    # raio de concordância) e intersecta os vizinhos: cantos vivos limpos
    lines = []
    for i0, i1 in zip(keep[:-1], keep[1:]):
        seg = curve[i0:i1 + 1]
        L = np.linalg.norm(seg[-1] - seg[0])
        margem = max(1, int(len(seg) * 0.15)) if L > 6 * cell_mm else 0
        core = seg[margem:len(seg) - margem] if len(seg) - 2 * margem >= 3 else seg
        c, dvec = _fit_line(core)
        if dvec @ (seg[-1] - seg[0]) < 0:
            dvec = -dvec
        nseg = cnorm[i0:i1 + 1].mean(0)
        lines.append((c, dvec, seg, nseg))
    verts = [lines[0][0] + lines[0][1] * float((curve[0] - lines[0][0]) @ lines[0][1])]
    for (c1, d1, _, _), (c2, d2, _, _) in zip(lines[:-1], lines[1:]):
        x_ = _intersect(c1, d1, c2, d2)
        verts.append(x_ if x_ is not None else (c1 + c2) / 2)
    cl, dl = lines[-1][0], lines[-1][1]
    verts.append(cl + dl * float((curve[-1] - cl) @ dl))
    verts = np.array(verts)
    # o raio de concordância parte uma reta em duas quase colineares: une
    while len(verts) > 2:
        dirs = np.diff(verts, axis=0)
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        turns = np.degrees(np.arccos(np.clip((dirs[:-1] * dirs[1:]).sum(1), -1, 1)))
        i = int(np.argmin(turns))
        if turns[i] >= 3.0:
            break
        verts = np.delete(verts, i + 1, axis=0)
        del lines[i + 1]
    # canto vivo arredondado pela média vira um trecho curtinho entre duas
    # retas longas: some, e as vizinhas se encontram no canto
    curto = 3.0 * cell_mm
    while len(verts) > 3:
        lens = np.linalg.norm(np.diff(verts, axis=0), axis=1)
        internos = [i for i in range(1, len(lens) - 1) if lens[i] < curto]
        if not internos:
            break
        i = min(internos, key=lambda j: lens[j])
        x_ = _intersect(lines[i - 1][0], lines[i - 1][1], lines[i + 1][0], lines[i + 1][1])
        if x_ is None:
            break
        verts = np.vstack([verts[:i], [x_], verts[i + 2:]])
        del lines[i]

    closed = bool(np.linalg.norm(curve[0] - curve[-1]) < 4 * cell_mm)
    if closed and len(lines) >= 4:
        # contorno fechado: o caminho começa no meio de um trecho e o parte em
        # dois (o 1º e o último) — vira um trecho só e os cantos saem cíclicos
        pts_m = np.vstack([lines[-1][2], lines[0][2]])
        c, dvec = _fit_line(pts_m)
        lines = [(c, dvec, pts_m, (lines[-1][3] + lines[0][3]) / 2)] + lines[1:-1]
        nl = len(lines)
        verts = []
        for i in range(nl):
            (c1, d1, _, _), (c2, d2, _, _) = lines[i - 1], lines[i]
            x_ = _intersect(c1, d1, c2, d2)
            verts.append(x_ if x_ is not None else (c1 + c2) / 2)
        verts = np.array(verts)
    else:
        closed = False if len(lines) < 4 else closed
    poly = np.vstack([verts, verts[:1]]) if closed else verts

    # rms da curva medida contra a polilinha de cantos vivos
    def _dist_poly(p):
        best = np.inf
        for i in range(len(poly) - 1):
            a_, b_ = poly[i], poly[i + 1]
            ab = b_ - a_
            t_ = np.clip(((p - a_) @ ab) / max(ab @ ab, 1e-12), 0, 1)
            best = min(best, float(np.linalg.norm(p - (a_ + t_ * ab))))
        return best
    amostra = curve[:: max(1, len(curve) // 1500)]
    devs = np.array([_dist_poly(p) for p in amostra])
    ruido = float(np.median(devs))

    # raio de concordância em cada canto interno: o arco tangente às duas
    # retas se afasta delas no máximo δ = R(1 - sen(θ/2)) (θ = ângulo interno)
    def _seg_dist(p, a_, b_):
        ab = b_ - a_
        t_ = np.clip(((p - a_) @ ab) / max(ab @ ab, 1e-12), 0, 1)
        return np.linalg.norm(p - (a_ + np.outer(t_, ab)), axis=1)

    dcurva, _ = cKDTree(curve).query(cpts)
    na_curva = dcurva < 2.0 * cell_mm
    cpts_curva = cpts[na_curva]
    ang_curva = np.degrees(np.arctan2(cnrm[na_curva, 1], cnrm[na_curva, 0]))

    def _ang_normal(k):
        return float(np.degrees(np.arctan2(lines[k % len(lines)][3][1], lines[k % len(lines)][3][0])))

    fillets = []
    n_v = len(verts)
    cantos = range(n_v) if closed else range(1, n_v - 1)
    for i in cantos:
        prev_, next_ = verts[(i - 1) % n_v], verts[(i + 1) % n_v]
        d1 = _unit(verts[i] - prev_)
        d2 = _unit(next_ - verts[i])
        turn = float(np.degrees(np.arccos(np.clip(d1 @ d2, -1, 1))))
        if turn < 10:
            continue
        theta_int = np.radians(180.0 - turn)
        rho = min(0.5 * np.linalg.norm(verts[i] - prev_),
                  0.5 * np.linalg.norm(next_ - verts[i]), 6.0)
        # mede nas células cruas (a curva afinada já vem com o canto comido),
        # só as que estão na curva — resto de parede de orelha infla o raio
        sel = np.linalg.norm(cpts_curva - verts[i], axis=1) < rho
        # o arco de concordância tem normal ENTRE as normais das duas retas;
        # parede de orelha que encosta no canto (normal fora disso) não conta
        a1, a2 = _ang_normal(i - 1), _ang_normal(i)
        meio = a1 + (((a2 - a1) + 180.0) % 360.0 - 180.0) / 2.0
        meia = abs(((a2 - a1) + 180.0) % 360.0 - 180.0) / 2.0 + 10.0
        sel &= np.abs(((ang_curva - meio) + 180.0) % 360.0 - 180.0) <= meia
        perto = cpts_curva[sel]
        if len(perto) < 3:
            continue
        dev = np.minimum(_seg_dist(perto, prev_, verts[i]), _seg_dist(perto, verts[i], next_))
        delta = float(np.percentile(dev, 95))
        if delta <= max(0.06, 3 * ruido):
            continue
        R = delta / (1.0 - np.sin(theta_int / 2.0))
        lim = 0.5 * min(np.linalg.norm(verts[i] - prev_), np.linalg.norm(next_ - verts[i]))
        R_max = lim * np.tan(theta_int / 2.0)
        if R < R_max:
            fillets.append({"vertex": i, "radius_mm": round(float(R), 3),
                            "turn_deg": round(turn, 1)})

    out = {
        "axis_point": [round(float(t), 4) for t in p0],
        "axis_dir": [round(float(t), 6) for t in a],
        "radial_dir": [round(float(t), 6) for t in u],
        "vertices_rz": [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in verts],
        "closed": closed,
        "fillets": fillets,
        "rms_mm": round(float(np.sqrt(np.mean(devs ** 2))), 4),
        "p95_mm": round(float(np.percentile(devs, 95)), 4),
        "points": int(len(curve)),
        "coverage_median": round(float(np.median(cov)), 3),
    }
    if thickness_mm and not closed:
        normals = [ln[3] for ln in lines]
        closed_poly, aviso = _offset_closure(verts, np.array(normals), float(thickness_mm))
        out["closed_vertices_rz"] = [[round(float(p[0]), 4), round(float(p[1]), 4)]
                                     for p in closed_poly[:-1]]
        out["thickness_mm"] = float(thickness_mm)
        if aviso:
            out["aviso"] = aviso
    return out


# ------------------------------------------------------------------- furos

def _circle_fit(p2: np.ndarray) -> tuple[np.ndarray, float, float]:
    A = np.column_stack([2 * p2, np.ones(len(p2))])
    s = np.linalg.lstsq(A, (p2 ** 2).sum(1), rcond=None)[0]
    c = s[:2]
    R = float(np.sqrt(max(s[2] + c @ c, 0.0)))
    rms = float(np.sqrt(np.mean((np.linalg.norm(p2 - c, axis=1) - R) ** 2)))
    return c, R, rms


def _angular_pattern(angles_deg: list[float], tol_deg: float) -> dict | None:
    """Menor N (posições igualmente espaçadas na volta) em que todos os
    ângulos caem num ponto da grade."""
    ang = np.asarray(angles_deg, float) % 360.0
    if len(ang) < 2:
        return None
    for N in range(len(ang), 361):
        pitch = 360.0 / N
        ph = np.radians((ang % pitch) / pitch * 360.0)
        start = (np.degrees(np.arctan2(np.sin(ph).mean(), np.cos(ph).mean())) / 360.0 * pitch) % pitch
        k = np.round((ang - start) / pitch) % N
        err = np.abs(((ang - start - k * pitch) + 180.0) % 360.0 - 180.0)
        if err.max() <= tol_deg and len(np.unique(k)) == len(ang):
            ocupadas = sorted(int(x) for x in k)
            faltando = [i for i in range(N) if i not in set(ocupadas)]
            return {"positions": N, "pitch_deg": round(pitch, 4),
                    "start_deg": round(float(start), 3),
                    "occupied": ocupadas, "missing": faltando,
                    "max_error_deg": round(float(err.max()), 3)}
    return None


def detect_holes(mesh: trimesh.Trimesh, axis_point=(0, 0, 0), axis_dir=(0, 0, 1),
                 pixel_mm: float = 0.25, min_diameter_mm: float = 1.0,
                 density_per_mm2: float = 16.0, max_points: int = 2_000_000,
                 group_tol_mm: float = 0.4, angle_tol_deg: float = 1.0,
                 region: dict | None = None) -> dict:
    """Furos passantes vistos ao longo do eixo, com Ø pelas paredes e padrão
    angular. Lacuna de scan (adesivo de alvo, reflexo) também é um vazio
    fechado — fica marcada com has_wall=False e não entra nos grupos."""
    from scipy import ndimage as nd
    from scipy.spatial import cKDTree

    p0 = np.asarray(axis_point, float)
    u, v, a = axis_frame(axis_dir)
    pts, nrm = _surface_samples(mesh, density_per_mm2, max_points, region)
    d = pts - p0
    x, y, z = d @ u, d @ v, d @ a
    lo = np.array([x.min(), y.min()]) - 3 * pixel_mm
    hi = np.array([x.max(), y.max()]) + 3 * pixel_mm
    shape = np.ceil((hi - lo) / pixel_mm).astype(int) + 1
    occ = np.zeros(shape, bool)
    occ[((x - lo[0]) / pixel_mm).astype(int), ((y - lo[1]) / pixel_mm).astype(int)] = True
    occ = nd.binary_closing(occ, iterations=2)
    lab, k = nd.label(~occ)
    border = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]))

    wall = np.abs(nrm @ a) < 0.3
    wall_xy = np.column_stack([x[wall], y[wall]])
    wall_z = z[wall]
    wtree = cKDTree(wall_xy) if len(wall_xy) else None

    holes = []
    for l in range(1, k + 1):
        if l in border:
            continue
        ii, jj = np.nonzero(lab == l)
        area = len(ii) * pixel_mm ** 2
        d_raster = 2 * np.sqrt(area / np.pi)
        if d_raster < min_diameter_mm:
            continue
        cx = lo[0] + (ii.mean() + 0.5) * pixel_mm
        cy = lo[1] + (jj.mean() + 0.5) * pixel_mm
        r_est = d_raster / 2
        entry = {"center_uv": [cx, cy], "diameter_mm": d_raster,
                 "raster_diameter_mm": round(float(d_raster), 3),
                 "has_wall": False, "rms_mm": None}
        if wtree is not None:
            # faixa estreita em volta da borda do raster: larga demais pega
            # a parede de outra coisa (furo central Ø53 saía Ø57,6)
            banda = min(max(0.8, 0.25 * r_est), 2.0)
            near = wtree.query_ball_point([cx, cy], r_est + banda + 1.0)
            near = [i for i in near
                    if abs(np.hypot(*(wall_xy[i] - [cx, cy])) - r_est) < banda]
            if len(near) >= 30:
                c2, R, rms = _circle_fit(wall_xy[near])
                # 2ª passada só com os pontos perto do círculo ajustado
                dd = np.abs(np.linalg.norm(wall_xy[near] - c2, axis=1) - R)
                sel = np.asarray(near)[dd < max(0.2, 3 * rms)]
                if len(sel) >= 20:
                    c2, R, rms = _circle_fit(wall_xy[sel])
                    ang = np.degrees(np.arctan2(wall_xy[sel, 1] - c2[1], wall_xy[sel, 0] - c2[0]))
                    span = len(np.unique(np.floor((ang % 360) / 10))) / 36.0
                    if span >= 0.5 and abs(2 * R - d_raster) < max(1.0, 0.05 * d_raster):
                        entry.update({"center_uv": [float(c2[0]), float(c2[1])],
                                      "diameter_mm": 2 * R, "has_wall": True,
                                      "rms_mm": round(rms, 4),
                                      "wall_z_mm": [round(float(wall_z[sel].min()), 3),
                                                    round(float(wall_z[sel].max()), 3)],
                                      "wall_coverage": round(span, 3)})
        cu, cv = entry["center_uv"]
        entry["radius_from_axis_mm"] = float(np.hypot(cu, cv))
        entry["angle_deg"] = float(np.degrees(np.arctan2(cv, cu)) % 360.0)
        pm = p0 + u * cu + v * cv
        entry["center_xyz"] = [round(float(t), 4) for t in pm]
        holes.append(entry)

    for h in holes:
        h["center_uv"] = [round(float(t), 4) for t in h["center_uv"]]
        h["diameter_mm"] = round(float(h["diameter_mm"]), 3)
        h["radius_from_axis_mm"] = round(h["radius_from_axis_mm"], 3)
        h["angle_deg"] = round(h["angle_deg"], 3)
    holes.sort(key=lambda h: (h["radius_from_axis_mm"], h["angle_deg"]))

    def _groups(key_fn, tol):
        reais = [h for h in holes if h["has_wall"] and h["radius_from_axis_mm"] > 1.0]
        gs: list[list[dict]] = []
        for h in reais:
            for g in gs:
                if all(abs(a_ - b_) <= tol for a_, b_ in zip(key_fn(h), key_fn(g[0]))):
                    g.append(h)
                    break
            else:
                gs.append([h])
        out = []
        for g in gs:
            if len(g) < 2:
                continue
            item = {"count": len(g),
                    "diameter_mm": round(float(np.mean([h["diameter_mm"] for h in g])), 3),
                    "pcd_mm": round(2 * float(np.mean([h["radius_from_axis_mm"] for h in g])), 3),
                    "angles_deg": sorted(h["angle_deg"] for h in g)}
            diams = [h["diameter_mm"] for h in g]
            if max(diams) - min(diams) > group_tol_mm:
                item["diameters_mm"] = sorted(round(x_, 3) for x_ in set(diams))
                item.pop("diameter_mm")
            pat = _angular_pattern(item["angles_deg"], angle_tol_deg)
            if pat:
                item["pattern"] = pat
            out.append(item)
        return out

    by_size = _groups(lambda h: (h["diameter_mm"], h["radius_from_axis_mm"]), group_tol_mm)
    by_circle = _groups(lambda h: (h["radius_from_axis_mm"],), max(group_tol_mm, 0.5))
    return {"axis_point": [round(float(t), 4) for t in p0],
            "axis_dir": [round(float(t), 6) for t in a],
            "radial_dir": [round(float(t), 6) for t in u],
            "holes": holes,
            "groups_by_size": by_size,
            "groups_by_circle": by_circle,
            "scan_gaps": sum(1 for h in holes if not h["has_wall"])}
