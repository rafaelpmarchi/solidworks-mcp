"""swengine — motor de geometria para engenharia reversa (scan -> SolidWorks).

Roda em processo separado do servidor MCP (venv próprio, Python 3.13).
Unidades: milímetros e graus em tudo que entra e sai.
As malhas nunca transitam por JSON: só caminhos de arquivo e metadados.
"""

__version__ = "0.1.0"
