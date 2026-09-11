"""
providers — Sistema multi-proveedor de subtítulos japoneses.

Cada proveedor implementa la clase base ``SubtitleProvider`` para
buscar, listar y descargar subtítulos de una fuente distinta.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses compartidas
# ---------------------------------------------------------------------------

@dataclass
class ShowMatch:
    """Resultado de búsqueda de un anime en un proveedor."""
    provider_name: str
    show_id: str            # ID interno del proveedor (entry id, URL, etc.)
    name: str               # Nombre principal del anime
    english_name: Optional[str] = None
    japanese_name: Optional[str] = None
    score: float = 0.0      # Puntuación de coincidencia (0.0 – 1.0)
    url: str = ""           # URL de referencia (para logging)


@dataclass
class SubtitleFile:
    """Referencia a un archivo de subtítulo disponible para descargar."""
    filename: str
    download_url: str
    episode: Optional[int] = None
    size: int = 0


# ---------------------------------------------------------------------------
# Clase base abstracta
# ---------------------------------------------------------------------------

class SubtitleProvider(ABC):
    """Interfaz que todo proveedor de subtítulos debe implementar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre legible del proveedor (para logging)."""
        ...

    @abstractmethod
    def search_show(self, anime_name: str) -> Optional[ShowMatch]:
        """
        Busca el anime en el proveedor y devuelve la mejor coincidencia.
        Retorna ``None`` si no se encuentra nada.
        """
        ...

    @abstractmethod
    def list_files(
        self, show: ShowMatch, episode: Optional[int] = None,
    ) -> list[SubtitleFile]:
        """
        Lista los archivos de subtítulo disponibles para un show.
        Si ``episode`` se proporciona, intentar filtrar por ese episodio.
        """
        ...

    @abstractmethod
    def download(self, subtitle: SubtitleFile, dest: Path) -> bool:
        """
        Descarga un archivo de subtítulo a ``dest``.
        Devuelve ``True`` si la descarga fue exitosa.
        """
        ...


# ---------------------------------------------------------------------------
# Importaciones públicas (lazy para evitar errores de import circular)
# ---------------------------------------------------------------------------

def get_providers() -> list[type[SubtitleProvider]]:
    """Devuelve la lista de clases de proveedores disponibles."""
    from providers.jimaku import JimakuProvider
    from providers.kitsunekko import KitsunekkoProvider
    return [JimakuProvider, KitsunekkoProvider]
