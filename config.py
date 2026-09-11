"""
config.py — Configuración centralizada para AniMerse.

Todas las rutas, constantes y parámetros del pipeline se definen aquí.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas del sistema de archivos
# ---------------------------------------------------------------------------
# Carpeta donde llegan los archivos recién descargados (cambiar según entorno).
SOURCE_DIR: Path = Path(os.environ.get(
    "ANIMERSE_SOURCE", os.path.expanduser("~/Downloads/Anime")
))

# Raíz de la biblioteca Jellyfin.
JELLYFIN_ROOT: Path = Path(os.environ.get(
    "ANIMERSE_DEST", os.path.expanduser("~/Jellyfin/Series")
))

# ---------------------------------------------------------------------------
# Extensiones de vídeo reconocidas
# ---------------------------------------------------------------------------
VIDEO_EXTENSIONS: set[str] = {".mkv", ".mp4", ".avi", ".webm", ".ts"}

# ---------------------------------------------------------------------------
# Proveedores de subtítulos japoneses
# ---------------------------------------------------------------------------
# Proveedor a usar: "jimaku", "kitsunekko" o "all" (prueba todos con fallback).
SUBTITLE_PROVIDER: str = os.environ.get("ANIMERSE_SUB_PROVIDER", "all")

# ---------------------------------------------------------------------------
# Kitsunekko
# ---------------------------------------------------------------------------
KITSUNEKKO_BASE_URL: str = "https://kitsunekko.net"
KITSUNEKKO_JP_DIR: str = f"{KITSUNEKKO_BASE_URL}/dirlist.php?dir=subtitles/japanese/"

# ---------------------------------------------------------------------------
# Jimaku.cc (API REST — requiere API key gratuita)
# ---------------------------------------------------------------------------
JIMAKU_BASE_URL: str = "https://jimaku.cc"
JIMAKU_API_URL: str = f"{JIMAKU_BASE_URL}/api"
JIMAKU_API_KEY: str = os.environ.get("ANIMERSE_JIMAKU_API_KEY", "")

# ---------------------------------------------------------------------------
# Extensiones reconocidas
# ---------------------------------------------------------------------------
# Extensiones de subtítulos que nos interesan.
SUBTITLE_EXTENSIONS: set[str] = {".srt", ".ass", ".ssa", ".sub", ".sup", ".idx"}

# Extensiones de archivos comprimidos.
ARCHIVE_EXTENSIONS: set[str] = {".zip", ".rar", ".7z"}

# ---------------------------------------------------------------------------
# Sincronización de subtítulos
# ---------------------------------------------------------------------------
# Herramienta de sincronización: "ffsubsync" o "alass".
SYNC_TOOL: str = os.environ.get("ANIMERSE_SYNC_TOOL", "ffsubsync")

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT: int = 30  # segundos
USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE: Path = Path(os.environ.get(
    "ANIMERSE_LOG", os.path.expanduser("~/animerse.log")
))
LOG_LEVEL: str = os.environ.get("ANIMERSE_LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Temporada por defecto
# ---------------------------------------------------------------------------
DEFAULT_SEASON: int = 1
