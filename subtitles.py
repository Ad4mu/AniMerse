"""
subtitles.py — Descarga de subtítulos japoneses desde Kitsunekko.

Flujo:
1. Buscar en el índice japonés de Kitsunekko una carpeta cuyo nombre
   coincida (fuzzy) con el anime.
2. Listar los archivos de esa carpeta.
3. Descargar el subtítulo cuyo número de episodio coincida.
4. Si el archivo descargado es un .zip/.rar, descomprimirlo y extraer
   el subtítulo correcto.
5. Renombrar el subtítulo para que coincida con el archivo de vídeo
   según el esquema Jellyfin con sufijo de idioma (.ja.srt/.ja.ass).
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    ARCHIVE_EXTENSIONS,
    KITSUNEKKO_BASE_URL,
    KITSUNEKKO_JP_DIR,
    REQUEST_TIMEOUT,
    SUBTITLE_EXTENSIONS,
    USER_AGENT,
)
from parser import EpisodeInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sesión HTTP reutilizable
# ---------------------------------------------------------------------------
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normaliza un string para comparación fuzzy (minúsculas, sin puntuación)."""
    text = unquote(text).lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_episode_number(filename: str) -> Optional[int]:
    """Intenta extraer un número de episodio del nombre de un archivo de subtítulo."""
    stem = Path(filename).stem

    # Patrones comunes en nombres de subtítulos de Kitsunekko
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
# Scraping de Kitsunekko
# ---------------------------------------------------------------------------

def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    """Descarga y parsea una página HTML; devuelve None si falla."""
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as exc:
        logger.error("Error al descargar %s: %s", url, exc)
        return None


def _find_show_folder(anime_name: str) -> Optional[str]:
    """
    Busca en el índice japonés de Kitsunekko la carpeta que mejor
    coincida con ``anime_name``.  Devuelve la URL completa o None.
    """
    soup = _fetch_page(KITSUNEKKO_JP_DIR)
    if soup is None:
        return None

    target = _normalize(anime_name)
    best_url: Optional[str] = None
    best_score: int = 0

    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        if "dirlist.php" not in href or "subtitles/japanese/" not in href:
            continue

        # Extraer el nombre de carpeta del enlace.
        folder_name = unquote(href.split("japanese/")[-1]).rstrip("/")
        if not folder_name:
            continue

        normalized_folder = _normalize(folder_name)

        # Coincidencia exacta → retorno inmediato.
        if normalized_folder == target:
            full_url = urljoin(KITSUNEKKO_BASE_URL + "/", href)
            logger.debug("Coincidencia exacta: %s", folder_name)
            return full_url

        # Coincidencia parcial (el target está contenido en la carpeta o viceversa).
        if target in normalized_folder or normalized_folder in target:
            score = len(normalized_folder)
            if score > best_score:
                best_score = score
                best_url = urljoin(KITSUNEKKO_BASE_URL + "/", href)

    if best_url:
        logger.debug("Mejor coincidencia parcial: %s", best_url)
    else:
        logger.warning("No se encontró carpeta en Kitsunekko para: %s", anime_name)

    return best_url


def _list_subtitle_files(folder_url: str) -> list[tuple[str, str]]:
    """
    Lista los archivos de subtítulo (y archivos comprimidos) dentro de
    una carpeta de Kitsunekko.

    Devuelve una lista de tuplas (nombre_archivo, url_descarga).
    """
    soup = _fetch_page(folder_url)
    if soup is None:
        return []

    results: list[tuple[str, str]] = []
    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        filename = unquote(href.split("/")[-1])
        ext = Path(filename).suffix.lower()
        if ext in SUBTITLE_EXTENSIONS or ext in ARCHIVE_EXTENSIONS:
            download_url = urljoin(KITSUNEKKO_BASE_URL + "/", href)
            results.append((filename, download_url))

    logger.debug("Archivos encontrados en %s: %d", folder_url, len(results))
    return results


def _download_file(url: str, dest: Path) -> bool:
    """Descarga un archivo binario a disco."""
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        return True
    except requests.RequestException as exc:
        logger.error("Error al descargar %s: %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# Extracción de archivos comprimidos
# ---------------------------------------------------------------------------

def _extract_subtitles_from_archive(
    archive_path: Path,
    target_episode: int,
) -> Optional[Path]:
    """
    Extrae un subtítulo con el episodio correcto de un .zip o .rar.
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
# API pública
# ---------------------------------------------------------------------------

def download_subtitle(info: EpisodeInfo) -> Optional[Path]:
    """
    Busca, descarga y renombra el subtítulo japonés para el episodio dado.

    Devuelve la ruta al archivo de subtítulo final (ya renombrado junto
    al vídeo) o ``None`` si no se encontró / falló la descarga.
    """
    logger.info(
        "Buscando subtítulo japonés: %s S%02dE%02d",
        info.anime_name, info.season, info.episode,
    )

    folder_url = _find_show_folder(info.anime_name)
    if folder_url is None:
        return None

    files = _list_subtitle_files(folder_url)
    if not files:
        logger.warning("No se encontraron subtítulos en: %s", folder_url)
        return None

    # ── Buscar coincidencia directa por número de episodio ────────────────
    subtitle_path: Optional[Path] = None

    for filename, url in files:
        ext = Path(filename).suffix.lower()
        ep = _extract_episode_number(filename)

        if ep == info.episode:
            if ext in SUBTITLE_EXTENSIONS:
                # Subtítulo directo.
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if _download_file(url, tmp):
                    subtitle_path = tmp
                    break
            elif ext in ARCHIVE_EXTENSIONS:
                # Archivo comprimido que contiene subtítulos.
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if _download_file(url, tmp):
                    extracted = _extract_subtitles_from_archive(tmp, info.episode)
                    if extracted:
                        subtitle_path = extracted
                    tmp.unlink(missing_ok=True)
                    if subtitle_path:
                        break

    # ── Fallback: descargar un paquete .zip genérico del show ─────────────
    if subtitle_path is None:
        for filename, url in files:
            ext = Path(filename).suffix.lower()
            if ext in ARCHIVE_EXTENSIONS:
                logger.info("Intentando paquete genérico: %s", filename)
                tmp = Path(tempfile.mktemp(suffix=ext, prefix="animerse_"))
                if _download_file(url, tmp):
                    extracted = _extract_subtitles_from_archive(tmp, info.episode)
                    if extracted:
                        subtitle_path = extracted
                    tmp.unlink(missing_ok=True)
                    if subtitle_path:
                        break

    if subtitle_path is None:
        logger.warning(
            "No se encontró subtítulo para %s E%02d", info.anime_name, info.episode
        )
        return None

    # ── Renombrar al esquema Jellyfin ─────────────────────────────────────
    sub_ext = subtitle_path.suffix  # .srt o .ass
    video_dir = info.original_path.parent
    final_name = f"{info.original_path.stem}.ja{sub_ext}"
    final_path = video_dir / final_name

    # Mover el subtítulo al lado del vídeo.
    import shutil
    shutil.move(str(subtitle_path), str(final_path))
    logger.info("Subtítulo guardado: %s", final_path.name)

    return final_path
