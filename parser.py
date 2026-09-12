"""
parser.py — Análisis de nombres de archivo de anime.

Extrae nombre del anime, año (opcional), número de temporada y número de
episodio a partir de los patrones más habituales usados por los grupos de
fansub y escenas de release:

  [SubGroup] Anime Name - 05 (1080p) [HASH].mkv
  Anime Name S02E10.mkv
  Anime.Name.-.12.(720p).mkv
  Anime Name - Episode 07.mkv
  [SubGroup] Anime Name (2023) - 05.mkv
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class EpisodeInfo:
    """Resultado del análisis de un nombre de archivo."""
    anime_name: str
    episode: int
    season: int
    year: Optional[int]
    original_path: Path


# ---------------------------------------------------------------------------
# Patrones ordenados de más específico a más genérico.
# Se aplica el primero que haga match.
# ---------------------------------------------------------------------------
_PATTERNS: list[re.Pattern[str]] = [
    # [Group] Name - S01E05 ...
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?-?\s*"
        r"S(?P<season>\d{1,2})E(?P<episode>\d{1,4})",
        re.IGNORECASE,
    ),
    # Name 第01話 (Japanese for Episode 01)
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?"
        r"第(?P<episode>\d{1,4})話",
        re.IGNORECASE,
    ),
    # [Group] Name - 05 ...  (sin indicador de temporada explícito)
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?-\s*"
        r"(?P<episode>\d{2,4})"
        r"(?:\s|\(|\.|\[|v\d|$)",
        re.IGNORECASE,
    ),
    # Name.-.12.(720p)  (puntos como separadores)
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?[\.\s]-?[\.\s]?"
        r"(?P<episode>\d{2,4})"
        r"(?:\s|\(|\.|\[|v\d|$)",
        re.IGNORECASE,
    ),
    # Name Episode 07  /  Name EP07  /  Name Ep. 07
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?"
        r"(?:Episode|Ep\.?)\s*"
        r"(?P<episode>\d{1,4})",
        re.IGNORECASE,
    ),
    # Name E07  (sin S)
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?)\s*"
        r"(?:\((?P<year>\d{4})\)\s*)?-?\s*"
        r"E(?P<episode>\d{1,4})"
        r"(?:\s|\(|\.|\[|$)",
        re.IGNORECASE,
    ),
    # Name01 / Name 01 (Fallbacks without explicit separators/tags like "Episode", "E", or "-")
    # Requiring at least 1 letter at the end of the name part to avoid matching numbers in anime name if not space-separated.
    re.compile(
        r"(?:\[.*?\]\s*)?"
        r"(?P<name>.+?[a-zA-Z])"
        r"(?P<episode>\d{1,4})"
        r"(?:\s|\(|\.|\[|v\d|$)",
        re.IGNORECASE,
    ),
]


def _clean_name(raw: str) -> str:
    """Limpia el nombre del anime eliminando separadores residuales."""
    # Reemplazar puntos y guiones bajos por espacios.
    name = raw.replace("_", " ").replace(".", " ")
    # Eliminar etiquetas de grupo residuales [xxx].
    name = re.sub(r"\[.*?\]", "", name)
    # Colapsar espacios múltiples y recortar.
    name = re.sub(r"\s{2,}", " ", name).strip(" -")
    return name


def parse_filename(filepath: Path) -> Optional[EpisodeInfo]:
    """
    Analiza el nombre de archivo y devuelve un ``EpisodeInfo`` o ``None``
    si no se pudo interpretar.
    """
    stem = filepath.stem  # nombre sin extensión

    for pattern in _PATTERNS:
        match = pattern.search(stem)
        if not match:
            continue

        groups = match.groupdict()
        anime_name = _clean_name(groups["name"])
        episode = int(groups["episode"])
        season = int(groups.get("season") or 0) or None  # 0 → None
        year_str = groups.get("year")
        year = int(year_str) if year_str else None

        if not anime_name or episode < 0:
            continue

        return EpisodeInfo(
            anime_name=anime_name,
            episode=episode,
            season=season or 1,  # temporada por defecto
            year=year,
            original_path=filepath,
        )

    return None
