"""
subtitles.py — Descarga de subtítulos japoneses usando múltiples proveedores.

Flujo:
1. Construir la lista de proveedores a intentar según SUBTITLE_PROVIDER.
2. Para cada proveedor:
   a. Buscar el anime (fuzzy match).
   b. Listar archivos del anime encontrado.
   c. Buscar un archivo que coincida con el episodio (o descargar un zip genérico).
   d. Descargar el archivo.
   e. Si es un archivo comprimido, extraer el subtítulo correcto.
3. Si la descarga tiene éxito, renombrar el subtítulo para que coincida con 
   el archivo de vídeo según el esquema Jellyfin con sufijo de idioma (.ja.srt).
4. Si un proveedor falla, pasar al siguiente.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import zipfile
import shutil
from pathlib import Path
from typing import Optional

from config import (
    ARCHIVE_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    SUBTITLE_PROVIDER,
)
from parser import EpisodeInfo
from providers import get_providers, SubtitleProvider, SubtitleFile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _extract_episode_number(filename: str) -> Optional[int]:
    """Intenta extraer un número de episodio del nombre de un archivo de subtítulo."""
    stem = Path(filename).stem
    patterns = [
        r"[Ee][Pp]?\.?\s*(\d{1,4})",          # E05, Ep05, EP.05
        r"S\d{1,2}E(\d{1,4})",                # S01E05
        r"[\s_\-.](\d{2,4})[\s_\-.\[\(v]",    # - 05 - , _05_, .05.
        r"[\s_\-.](\d{2,4})$",                 # ...05 (al final)
        r"#(\d{1,4})",                          # #05
        r"(?:Episode|ep)\s*(\d{1,4})",         # Episode 05
    ]
    for pattern in patterns:
        m = re.search(pattern, stem, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Extracción de archivos comprimidos
# ---------------------------------------------------------------------------

def _extract_subtitles_from_archive(
    archive_path: Path,
    target_episode: int,
) -> Optional[Path]:
    """
    Extrae un subtítulo con el episodio correcto de un archivo comprimido.
    Devuelve la ruta al archivo extraído o None.
    """
    ext = archive_path.suffix.lower()
    tmp_dir = Path(tempfile.mkdtemp(prefix="animerse_"))

    try:
        if ext == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmp_dir)
        elif ext == ".rar":
            try:
                import rarfile
                with rarfile.RarFile(archive_path, "r") as rf:
                    rf.extractall(tmp_dir)
            except ImportError:
                logger.error(
                    "El paquete 'rarfile' no está instalado. "
                    "Instálalo con: pip install rarfile  "
                    "y asegúrate de tener 'unrar' en el sistema."
                )
                return None
        elif ext == ".7z":
            try:
                import py7zr
                with py7zr.SevenZipFile(archive_path, mode='r') as z:
                    z.extractall(path=tmp_dir)
            except ImportError:
                logger.error(
                    "El paquete 'py7zr' no está instalado. "
                    "Instálalo con: pip install py7zr"
                )
                return None
        else:
            return None

        # Buscar entre los archivos extraídos el que coincida con el episodio.
        candidates: list[Path] = []
        for root, _dirs, files in os.walk(tmp_dir):
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in SUBTITLE_EXTENSIONS:
                    ep = _extract_episode_number(fname)
                    if ep == target_episode:
                        candidates.append(fpath)

        if not candidates:
            # Si no se pudo detectar el episodio, devolver el primero encontrado.
            for root, _dirs, files in os.walk(tmp_dir):
                for fname in files:
                    fpath = Path(root) / fname
                    if fpath.suffix.lower() in SUBTITLE_EXTENSIONS:
                        return fpath
            return None

        return candidates[0]

    except Exception:
        logger.exception("Error al extraer %s", archive_path.name)
        return None


# ---------------------------------------------------------------------------
# Motor principal de descarga
# ---------------------------------------------------------------------------

def _try_download_from_provider(
    provider: SubtitleProvider, info: EpisodeInfo
) -> Optional[Path]:
    """Intenta descargar un subtítulo usando un proveedor específico."""
    logger.debug("[%s] Buscando '%s'...", provider.name, info.anime_name)
    show = provider.search_show(info.anime_name)
    if not show:
        return None

    # Listar archivos filtrando por episodio si es posible
    files = provider.list_files(show, info.episode)
    if not files:
        # Algunos proveedores pueden fallar el filtrado, intentemos listar todos
        files = provider.list_files(show)
        if not files:
            logger.warning("[%s] No se encontraron archivos para: %s", provider.name, show.name)
            return None

    subtitle_path: Optional[Path] = None

    # 1. Buscar coincidencia directa por número de episodio
    for f in files:
        ext = Path(f.filename).suffix.lower()
        ep = _extract_episode_number(f.filename)

        if ep == info.episode:
            if ext in SUBTITLE_EXTENSIONS:
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if provider.download(f, tmp):
                    subtitle_path = tmp
                    break
            elif ext in ARCHIVE_EXTENSIONS:
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if provider.download(f, tmp):
                    extracted = _extract_subtitles_from_archive(tmp, info.episode)
                    if extracted:
                        subtitle_path = extracted
                    tmp.unlink(missing_ok=True)
                    if subtitle_path:
                        break

    # 2. Fallback: descargar un paquete genérico (.zip, .7z, etc.)
    if subtitle_path is None:
        for f in files:
            ext = Path(f.filename).suffix.lower()
            if ext in ARCHIVE_EXTENSIONS:
                logger.debug("[%s] Intentando paquete genérico: %s", provider.name, f.filename)
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if provider.download(f, tmp):
                    extracted = _extract_subtitles_from_archive(tmp, info.episode)
                    if extracted:
                        subtitle_path = extracted
                    tmp.unlink(missing_ok=True)
                    if subtitle_path:
                        break

    return subtitle_path


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def download_subtitle(info: EpisodeInfo) -> Optional[Path]:
    """
    Busca, descarga y renombra el subtítulo japonés para el episodio dado
    usando los proveedores configurados.

    Devuelve la ruta al archivo de subtítulo final (ya renombrado junto
    al vídeo) o ``None`` si fallaron todos los proveedores.
    """
    logger.info(
        "Buscando subtítulo japonés: %s S%02dE%02d",
        info.anime_name, info.season, info.episode,
    )

    # Determinar qué proveedores usar
    provider_classes = get_providers()
    active_providers: list[SubtitleProvider] = []
    
    for cls in provider_classes:
        provider_inst = cls()
        name_key = provider_inst.name.lower()
        if SUBTITLE_PROVIDER == "all":
            active_providers.append(provider_inst)
        elif name_key.startswith(SUBTITLE_PROVIDER.lower()):
            active_providers.append(provider_inst)
            
    if not active_providers:
        logger.error("No hay proveedores activos para: %s", SUBTITLE_PROVIDER)
        return None

    # Intentar descargar
    subtitle_path: Optional[Path] = None
    
    for provider in active_providers:
        logger.info("Intentando con proveedor: %s", provider.name)
        subtitle_path = _try_download_from_provider(provider, info)
        if subtitle_path:
            logger.info("✔ Subtítulo encontrado con %s", provider.name)
            break
        else:
            logger.info("✘ Falló con %s", provider.name)

    if subtitle_path is None:
        logger.warning(
            "Ningún proveedor pudo encontrar subtítulo para %s E%02d",
            info.anime_name, info.episode
        )
        return None

    # Renombrar al esquema Jellyfin
    sub_ext = subtitle_path.suffix  # .srt o .ass
    video_dir = info.original_path.parent
    final_name = f"{info.original_path.stem}.ja{sub_ext}"
    final_path = video_dir / final_name

    # Mover el subtítulo al lado del vídeo
    shutil.move(str(subtitle_path), str(final_path))
    logger.info("Subtítulo guardado: %s", final_path.name)

    return final_path
