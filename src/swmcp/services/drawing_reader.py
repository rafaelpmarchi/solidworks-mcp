"""Serviço de leitura: abre (se preciso), lê e restaura o estado (RNF-04)."""

from __future__ import annotations

import os

from swmcp.com.invoke import com_call
from swmcp.com.session import SwSession
from swmcp.com.wrappers import document as doc_w
from swmcp.com.wrappers import drawing as drawing_w
from swmcp.com.wrappers import model as model_w
from swmcp.domain.drawing import DrawingDump
from swmcp.domain.model import ModelProperties


def get_drawing_dump(session: SwSession, path: str) -> DrawingDump:
    """Dump completo de um .SLDDRW. Abre somente-leitura se não estiver aberto;
    se este serviço abriu o arquivo, ele fecha ao final (sem salvar)."""
    path = os.path.abspath(path)

    def work(app):
        doc = doc_w.find_open_document(app, path)
        opened_here = doc is None
        if opened_here:
            doc_w.open_document(app, path, read_only=True)
            doc = doc_w.find_open_document(app, path)
        try:
            return drawing_w.read_drawing(doc, path)
        finally:
            if opened_here:
                doc_w.close_document(app, com_call(doc, "GetTitle"))

    return session.run(work)


def get_model_properties(session: SwSession, path: str) -> ModelProperties:
    """Propriedades do modelo 3D. Mesma política de abrir/fechar do dump."""
    path = os.path.abspath(path)

    def work(app):
        doc = doc_w.find_open_document(app, path)
        opened_here = doc is None
        if opened_here:
            doc_w.open_document(app, path, read_only=True)
            doc = doc_w.find_open_document(app, path)
        try:
            return model_w.read_model(doc, path)
        finally:
            if opened_here:
                doc_w.close_document(app, com_call(doc, "GetTitle"))

    return session.run(work)
