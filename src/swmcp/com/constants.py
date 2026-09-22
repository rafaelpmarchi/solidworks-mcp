"""Constantes da API do SolidWorks usadas pelo projeto.

Cada bloco cita o enum de origem na documentação da API
(help.solidworks.com → SOLIDWORKS API Help → swconst).
Adicionar aqui somente o que o código usa — com nome e fonte.
"""

# swDocumentTypes_e
swDocNONE = 0
swDocPART = 1
swDocASSEMBLY = 2
swDocDRAWING = 3

DOC_TYPE_NAMES = {
    swDocNONE: "none",
    swDocPART: "part",
    swDocASSEMBLY: "assembly",
    swDocDRAWING: "drawing",
}

DOC_TYPE_BY_EXTENSION = {
    ".sldprt": swDocPART,
    ".sldasm": swDocASSEMBLY,
    ".slddrw": swDocDRAWING,
    ".sldlfp": swDocPART,  # library feature part (perfil de weldment) abre como peça
}

# Documentos de biblioteca que o SolidWorks abre sozinho, em segundo plano,
# quando uma feature os referencia (perfis de weldment .sldlfp, por exemplo).
# Aparecem em ISldWorks::GetDocuments mas não são trabalho do usuário.
LIBRARY_FEATURE_EXTENSIONS = frozenset({".sldlfp"})


def is_library_document(path: str | None) -> bool:
    """True para perfil de weldment/library feature part carregado por referência."""
    if not path:
        return False
    return path.rsplit(".", 1)[-1].lower() in {e.lstrip(".") for e in LIBRARY_FEATURE_EXTENSIONS}


# swOpenDocOptions_e
swOpenDocOptions_Silent = 0x1
swOpenDocOptions_ReadOnly = 0x2

# swSaveAsVersion_e / swSaveAsOptions_e (fase de escrita — ainda não usados)

# swFileLoadError_e — só os bits confirmados na documentação; o restante é
# reportado como valor bruto (nunca mascarar: RNF-01/R4)
FILE_LOAD_ERRORS = {
    0x1: "swGenericError",
    0x2: "swFileNotFoundError",
    0x80: "swFutureVersion — arquivo salvo em versão mais nova do SolidWorks",
    0x2000: "swFileCriticalDataRepairError — arquivo corrompido",
}

# swFileLoadWarning_e — idem: apenas confirmados
FILE_LOAD_WARNINGS = {
    0x1: "swFileLoadWarning_IdMismatch",
    0x2: "swFileLoadWarning_ReadOnly — aberto somente-leitura",
    0x4: "swFileLoadWarning_SharingViolation — aberto por outro usuário",
    0x8: "swFileLoadWarning_DrawingANSIUpdate",
    0x20: "swFileLoadWarning_DrawingsOnlyRapidDraft",
    0x40: "swFileLoadWarning_ViewOnlyRestrictions",
}


def decode_bits(value: int, table: dict[int, str]) -> list[str]:
    """Decompõe um bitmask nos nomes conhecidos; bits desconhecidos viram hex."""
    names = [name for bit, name in table.items() if value & bit]
    known = 0
    for bit in table:
        known |= bit
    unknown = value & ~known
    if unknown:
        names.append(f"bits não mapeados: 0x{unknown:X}")
    return names

# ISldWorks::RevisionNumber → ano comercial (23 = SolidWorks 2015)
_REVISION_BASE_MAJOR = 23
_REVISION_BASE_YEAR = 2015


def revision_to_year(revision: str) -> int | None:
    """"33.2.0" → 2025. None se o formato for inesperado."""
    try:
        major = int(revision.split(".")[0])
    except (ValueError, AttributeError, IndexError):
        return None
    return _REVISION_BASE_YEAR + (major - _REVISION_BASE_MAJOR)


# ------------------------------------------------------------------ esboço

# swUserPreferenceToggle_e — snaps que ARREDONDAM a geometria criada por API.
# Medido no SW2023: com eles ligados, CreateLine/CreateCornerRectangle aceitam
# as coordenadas e devolvem outras (Ø67,6 → 70; y=55 encostado num Ø120 → 60),
# sem erro nenhum. Desligados durante o desenho, a geometria sai exata.
SKETCH_SNAP_TOGGLES = (
    "swSketchSnapsNearest",
    "swSketchSnapsPoints",
    "swSketchSnapsCenterPoints",
    "swSketchSnapsQuadrantPoints",
    "swSketchSnapsMidPoints",
    "swSketchSnapsIntersections",
    "swSketchSnapsHVPoints",
    "swSketchSnapsHVLines",
    "swSketchSnapsLength",
    "swSketchSnapsGrid",
    "swSketchSnapsTangent",
    "swSketchSnapsPerpendicular",
    "swSketchSnapsParallel",
    "swSketchInferFromModel",
)

# Estes precisam ficar LIGADOS: são eles que unem os endpoints coincidentes de
# linhas criadas em chamadas separadas. Sem eles cada linha fica solta (N
# segmentos = 2N pontos, contorno aberto) e FeatureRevolve2/FeatureCut4
# devolvem None sem explicação.
SKETCH_MERGE_TOGGLES = (
    "swSketchInference",
    "swSketchAutomaticRelations",
)

# Tolerância de conferência da geometria de esboço (mm). Abaixo disso é ruído
# numérico da conversão m↔mm; acima, algum snap mexeu no que foi pedido.
SKETCH_TOLERANCE_MM = 1e-4

# swAdvWzdHoleTypes_e — tipos do assistente de furação no modo LEGADO, o único
# que obedece aos parâmetros passados quando o Toolbox não está instalado (aí a
# base de tamanhos não responde e as normas ISO/DIN/ANSI geram um furo em
# polegada, com o NOME certo e a geometria errada).
ADV_WIZARD_HOLE_TYPES = {
    "simple": "swAdvWzdStraight",
    "tap": "swAdvWzdStraightTap",
    "counterbore": "swAdvWzdCounterBore",
    "countersink": "swAdvWzdCounterSink",
    "taper_tap": "swAdvWzdTaperTap",
}
