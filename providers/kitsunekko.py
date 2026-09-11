"""
providers/kitsunekko.py — Proveedor de subtítulos vía scraping de Kitsunekko.

Mejoras respecto al scraper original:
  • Parseo correcto de la estructura HTML real (<table id="flisttable">)
  • Fuzzy matching mejorado con difflib SequenceMatcher
  • Reintentos con backoff exponencial
  • Manejo correcto de URLs codificadas
"""

from __future__ import annotations

import logging
import re
import time
from difflib import SequenceMatcher
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
from providers import ShowMatch, SubtitleFile, SubtitleProvider

logger = logging.getLogger(__name__)

# Número máximo de reintentos y backoff base.
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normaliza un string para comparación fuzzy (minúsculas, sin puntuación)."""
    text = unquote(text).lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """Calcula similitud entre dos strings normalizados (0.0 – 1.0)."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _extract_episode_number(filename: str) -> Optional[int]:
    """Intenta extraer un número de episodio del nombre de un archivo de subtítulo."""
    stem = Path(filename).stem

    patterns = [
        r"[Ee][Pp]?\.?\s*(\d{1,4})",
        r"S\d{1,2}E(\d{1,4})",
        r"[\s_\-.](\d{2,4})[\s_\-.\[\(v]",
        r"[\s_\-.](\d{2,4})$",
        r"#(\d{1,4})",
        r"(?:Episode|ep)\s*(\d{1,4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, stem, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Sesión HTTP con reintentos
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    """
    Descarga y parsea una página HTML de Kitsunekko con reintentos.
    Devuelve None si todos los intentos fallan.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = _session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as exc:
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                logger.warning(
                    "Kitsunekko: intento %d/%d falló para %s (%s), "
                    "reintentando en %.0fs…",
                    attempt, _MAX_RETRIES, url, exc, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "Kitsunekko: todos los intentos fallaron para %s: %s",
                    url, exc,
                )
    return None


# ---------------------------------------------------------------------------
# Proveedor Kitsunekko
# ---------------------------------------------------------------------------

class KitsunekkoProvider(SubtitleProvider):
    """Proveedor de subtítulos japoneses vía scraping de Kitsunekko.net."""

    @property
    def name(self) -> str:
        return "Kitsunekko"

    # ------------------------------------------------------------------
    # Búsqueda de carpeta
    # ------------------------------------------------------------------

    def search_show(self, anime_name: str) -> Optional[ShowMatch]:
        soup = _fetch_page(KITSUNEKKO_JP_DIR)
        if soup is None:
            return None

        target = _normalize(anime_name)
        best_match: Optional[ShowMatch] = None
        best_score: float = 0.0

        # Kitsunekko usa una tabla con id="flisttable".
        # Cada fila <tr> contiene un <td> con un <a> al directorio.
        # Formato del href: /dirlist.php?dir=subtitles%2Fjapanese%2F{folder}%2F
        table = soup.find("table", id="flisttable")
        links = table.find_all("a", href=True) if table else soup.find_all("a", href=True)

        for link in links:
            href: str = link["href"]

            # Solo enlaces a directorios de subtítulos japoneses.
            if "dirlist.php" not in href:
                continue
            if "japanese" not in href.lower():
                continue

            # Extraer nombre de carpeta.
            # El href tiene formato: /dirlist.php?dir=subtitles%2Fjapanese%2FFolder+Name%2F
            folder_part = href.split("japanese")[-1]
            # Eliminar %2F inicial y final
            folder_part = folder_part.lstrip("%2F").lstrip("/").rstrip("%2F").rstrip("/")
            folder_name = unquote(folder_part).replace("+", " ").strip()

            if not folder_name:
                continue

            normalized_folder = _normalize(folder_name)

            # --- Puntuación ---

            # Coincidencia exacta → retorno inmediato.
            if normalized_folder == target:
                logger.debug("Kitsunekko: coincidencia exacta: %s", folder_name)
                full_url = urljoin(KITSUNEKKO_BASE_URL, href)
                return ShowMatch(
                    provider_name=self.name,
                    show_id=href,
                    name=folder_name,
                    score=1.0,
                    url=full_url,
                )

            # Similitud fuzzy con SequenceMatcher.
            sim = _similarity(anime_name, folder_name)

            # Bonus por containment (uno contiene al otro).
            if target in normalized_folder or normalized_folder in target:
                sim = max(sim, 0.80)

            if sim > best_score:
                best_score = sim
                full_url = urljoin(KITSUNEKKO_BASE_URL, href)
                best_match = ShowMatch(
                    provider_name=self.name,
                    show_id=href,
                    name=folder_name,
                    score=sim,
                    url=full_url,
                )

        if best_match and best_match.score >= 0.55:
            logger.info(
                "Kitsunekko: mejor coincidencia: '%s' (score=%.2f)",
                best_match.name, best_match.score,
            )
            return best_match

        logger.warning(
            "Kitsunekko: no se encontró coincidencia suficiente para '%s' "
            "(mejor score=%.2f)",
            anime_name, best_score,
        )
        return None

    # ------------------------------------------------------------------
    # Listado de archivos
    # ------------------------------------------------------------------

    def list_files(
        self, show: ShowMatch, episode: Optional[int] = None,
    ) -> list[SubtitleFile]:
        soup = _fetch_page(show.url)
        if soup is None:
            return []

        results: list[SubtitleFile] = []

        # Buscar en la tabla de archivos.
        table = soup.find("table", id="flisttable")
        links = table.find_all("a", href=True) if table else soup.find_all("a", href=True)

        for link in links:
            href: str = link["href"]

            # Extraer nombre de archivo del href.
            filename = unquote(href.split("/")[-1])
            if not filename:
                # Intentar desde el texto del link.
                filename = link.get_text(strip=True)
            if not filename:
                continue

            ext = Path(filename).suffix.lower()
            if ext not in SUBTITLE_EXTENSIONS and ext not in ARCHIVE_EXTENSIONS:
                continue

            # Construir URL de descarga.
            if href.startswith("http"):
                download_url = href
            else:
                download_url = urljoin(KITSUNEKKO_BASE_URL, href)

            ep = _extract_episode_number(filename)
            results.append(SubtitleFile(
                filename=filename,
                download_url=download_url,
                episode=ep,
            ))

        logger.debug(
            "Kitsunekko: %d archivos encontrados en %s", len(results), show.url,
        )
        return results

    # ------------------------------------------------------------------
    # Descarga
    # ------------------------------------------------------------------

    def download(self, subtitle: SubtitleFile, dest: Path) -> bool:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = _session.get(
                    subtitle.download_url,
                    timeout=REQUEST_TIMEOUT,
                    stream=True,
                )
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        fh.write(chunk)
                logger.debug(
                    "Kitsunekko: descargado %s → %s",
                    subtitle.filename, dest.name,
                )
                return True

            except requests.RequestException as exc:
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE ** attempt
                    logger.warning(
                        "Kitsunekko: error descargando %s (intento %d/%d): %s, "
                        "reintentando en %.0fs…",
                        subtitle.filename, attempt, _MAX_RETRIES, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "Kitsunekko: fallo definitivo descargando %s: %s",
                        subtitle.filename, exc,
                    )
        return False
