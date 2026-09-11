"""
providers/jimaku.py — Proveedor de subtítulos usando la API REST de Jimaku.cc.

Jimaku es un sitio comunitario con una API REST formal que permite buscar
anime por nombre (romaji, inglés o japonés), listar archivos con filtro
por episodio y descargar subtítulos directamente.

Requiere una API key gratuita (variable de entorno ANIMERSE_JIMAKU_API_KEY).
"""

from __future__ import annotations

import logging
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import requests

from config import (
    JIMAKU_API_KEY,
    JIMAKU_API_URL,
    JIMAKU_BASE_URL,
    REQUEST_TIMEOUT,
    SUBTITLE_EXTENSIONS,
    ARCHIVE_EXTENSIONS,
    USER_AGENT,
)
from providers import ShowMatch, SubtitleFile, SubtitleProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normaliza un string para comparación fuzzy."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """Calcula similitud entre dos strings normalizados (0.0 – 1.0)."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _extract_episode_number(filename: str) -> Optional[int]:
    """Intenta extraer un número de episodio del nombre de un archivo."""
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
# Proveedor Jimaku
# ---------------------------------------------------------------------------

class JimakuProvider(SubtitleProvider):
    """Proveedor de subtítulos japoneses vía la API REST de Jimaku.cc."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
        })
        if JIMAKU_API_KEY:
            self._session.headers["Authorization"] = JIMAKU_API_KEY

    @property
    def name(self) -> str:
        return "Jimaku.cc"

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _api_get(self, endpoint: str, params: dict | None = None) -> Optional[requests.Response]:
        """Hace un GET a la API de Jimaku con manejo de errores y rate limits."""
        url = f"{JIMAKU_API_URL}{endpoint}"
        try:
            resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            # Manejar rate limiting
            if resp.status_code == 429:
                reset_after = float(resp.headers.get("x-ratelimit-reset-after", "5"))
                logger.warning(
                    "Jimaku rate limit alcanzado, esperando %.1f segundos…",
                    reset_after,
                )
                time.sleep(reset_after + 0.5)
                resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 401:
                logger.error(
                    "Jimaku API: autenticación fallida. Verifica tu API key "
                    "(variable de entorno ANIMERSE_JIMAKU_API_KEY)."
                )
                return None

            resp.raise_for_status()
            return resp

        except requests.RequestException as exc:
            logger.error("Error en Jimaku API %s: %s", endpoint, exc)
            return None

    # ------------------------------------------------------------------
    # Implementación de SubtitleProvider
    # ------------------------------------------------------------------

    def search_show(self, anime_name: str) -> Optional[ShowMatch]:
        if not JIMAKU_API_KEY:
            logger.warning(
                "Jimaku API key no configurada. Establece la variable de "
                "entorno ANIMERSE_JIMAKU_API_KEY para usar Jimaku.cc."
            )
            return None

        resp = self._api_get("/entries/search", params={
            "query": anime_name,
            "anime": "true",
        })
        if resp is None:
            return None

        entries = resp.json()
        if not entries:
            logger.debug("Jimaku: no se encontraron resultados para '%s'", anime_name)
            return None

        # Encontrar la mejor coincidencia entre los resultados.
        best_match: Optional[ShowMatch] = None
        best_score: float = 0.0

        target_norm = _normalize(anime_name)

        for entry in entries:
            entry_id = entry.get("id")
            romaji_name = entry.get("name", "")
            english_name = entry.get("english_name")
            japanese_name = entry.get("japanese_name")

            # Calcular similitud contra todos los nombres disponibles.
            scores = [_similarity(anime_name, romaji_name)]
            if english_name:
                scores.append(_similarity(anime_name, english_name))
            if japanese_name:
                scores.append(_similarity(anime_name, japanese_name))

            # Bonus si el target está contenido en algún nombre o viceversa.
            for name_candidate in [romaji_name, english_name or "", japanese_name or ""]:
                norm_candidate = _normalize(name_candidate)
                if norm_candidate and (target_norm in norm_candidate or norm_candidate in target_norm):
                    scores.append(0.85)

            score = max(scores)

            if score > best_score:
                best_score = score
                best_match = ShowMatch(
                    provider_name=self.name,
                    show_id=str(entry_id),
                    name=romaji_name,
                    english_name=english_name,
                    japanese_name=japanese_name,
                    score=score,
                    url=f"{JIMAKU_BASE_URL}/entry/{entry_id}",
                )

        if best_match and best_match.score >= 0.4:
            logger.info(
                "Jimaku: coincidencia encontrada: '%s' (score=%.2f, id=%s)",
                best_match.name, best_match.score, best_match.show_id,
            )
            return best_match

        logger.debug(
            "Jimaku: sin coincidencia suficiente para '%s' (mejor score=%.2f)",
            anime_name, best_score,
        )
        return None

    def list_files(
        self, show: ShowMatch, episode: Optional[int] = None,
    ) -> list[SubtitleFile]:
        params: dict = {}
        if episode is not None:
            params["episode"] = episode

        resp = self._api_get(f"/entries/{show.show_id}/files", params=params)
        if resp is None:
            return []

        files_data = resp.json()
        results: list[SubtitleFile] = []

        for file_entry in files_data:
            filename = file_entry.get("name", "")
            download_url = file_entry.get("url", "")
            size = file_entry.get("size", 0)

            ext = Path(filename).suffix.lower()
            if ext not in SUBTITLE_EXTENSIONS and ext not in ARCHIVE_EXTENSIONS:
                continue

            ep = _extract_episode_number(filename)
            results.append(SubtitleFile(
                filename=filename,
                download_url=download_url,
                episode=ep,
                size=size,
            ))

        logger.debug(
            "Jimaku: %d archivos encontrados para entry %s (ep=%s)",
            len(results), show.show_id, episode,
        )
        return results

    def download(self, subtitle: SubtitleFile, dest: Path) -> bool:
        try:
            resp = self._session.get(
                subtitle.download_url,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    fh.write(chunk)
            logger.debug("Jimaku: descargado %s → %s", subtitle.filename, dest.name)
            return True

        except requests.RequestException as exc:
            logger.error("Jimaku: error al descargar %s: %s", subtitle.filename, exc)
            return False
