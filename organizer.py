"""
organizer.py — Renombrado y estructuración de archivos de vídeo
según el esquema de carpetas de Jellyfin.

Estructura resultante:
    ~/Jellyfin/Series/
    └── Anime Name (2023)/
        └── Season 01/
            └── Anime Name - S01E05.mkv
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from config import JELLYFIN_ROOT, DEFAULT_SEASON, VIDEO_EXTENSIONS, SOURCE_DIR
from parser import EpisodeInfo, parse_filename

logger = logging.getLogger(__name__)


def _build_dest_path(info: EpisodeInfo) -> Path:
    """Construye la ruta completa de destino para un episodio."""
    if info.year:
        show_folder = f"{info.anime_name} ({info.year})"
    else:
        show_folder = info.anime_name

    season_folder = f"Season {info.season:02d}"
    ext = info.original_path.suffix  # .mkv, .mp4, etc.
    filename = f"{info.anime_name} - S{info.season:02d}E{info.episode:02d}{ext}"

    return JELLYFIN_ROOT / show_folder / season_folder / filename


def organize_file(filepath: Path) -> EpisodeInfo | None:
    """
    Analiza, renombra y mueve un archivo de vídeo individual.

    Devuelve el ``EpisodeInfo`` enriquecido con la ruta final, o ``None``
    si no se pudo procesar.
    """
    if filepath.suffix.lower() not in VIDEO_EXTENSIONS:
        logger.debug("Extensión no reconocida, ignorando: %s", filepath.name)
        return None

    info = parse_filename(filepath)
    if info is None:
        logger.warning("No se pudo interpretar el nombre: %s", filepath.name)
        return None

    dest = _build_dest_path(info)

    # Crear directorios intermedios.
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        logger.info("El destino ya existe, omitiendo: %s", dest)
        # Actualizar la ruta para que los pasos siguientes usen la existente.
        info.original_path = dest
        return info

    logger.info("Moviendo: %s → %s", filepath.name, dest)
    shutil.move(str(filepath), str(dest))

    # Actualizar la ruta en el objeto para que los módulos posteriores la usen.
    info.original_path = dest
    return info


def scan_and_organize(source: Path | None = None) -> list[EpisodeInfo]:
    """
    Escanea la carpeta de origen y organiza todos los vídeos encontrados.
    Devuelve la lista de episodios procesados exitosamente.
    """
    source = source or SOURCE_DIR
    if not source.is_dir():
        logger.error("La carpeta de origen no existe: %s", source)
        return []

    results: list[EpisodeInfo] = []
    for f in sorted(source.iterdir()):
        if f.is_file():
            try:
                info = organize_file(f)
                if info:
                    results.append(info)
            except Exception:
                logger.exception("Error al organizar %s", f.name)

    logger.info("Organización completada: %d episodios procesados.", len(results))
    return results
