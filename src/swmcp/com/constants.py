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
