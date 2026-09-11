"""
sync.py — Sincronización automática de subtítulos con el vídeo.

Soporta dos backends:
  • ffsubsync  (Python, se instala con pip)
  • alass      (binario Rust, debe estar en $PATH)

El subtítulo sincronizado sobrescribe al original.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from config import SYNC_TOOL

logger = logging.getLogger(__name__)


def _sync_with_ffsubsync(video: Path, subtitle: Path) -> bool:
    """Sincroniza usando ``ffsubsync`` (alias ``ffs``)."""
    output = Path(tempfile.mktemp(suffix=subtitle.suffix, prefix="animerse_sync_"))
    cmd = [
        "ffsubsync",
        str(video),
        "-i", str(subtitle),
        "-o", str(output),
    ]
    logger.debug("Ejecutando: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutos máximo por episodio
        )
        if result.returncode != 0:
            logger.error("ffsubsync falló (rc=%d): %s", result.returncode, result.stderr)
            output.unlink(missing_ok=True)
            return False

        # Sobrescribir el subtítulo original con la versión sincronizada.
        shutil.move(str(output), str(subtitle))
        return True

    except FileNotFoundError:
        logger.error(
            "ffsubsync no encontrado. Instálalo con: pip install ffsubsync"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("ffsubsync excedió el tiempo límite para %s", video.name)
        output.unlink(missing_ok=True)
        return False
    except Exception:
        logger.exception("Error inesperado al ejecutar ffsubsync")
        output.unlink(missing_ok=True)
        return False


def _sync_with_alass(video: Path, subtitle: Path) -> bool:
    """Sincroniza usando ``alass``."""
    output = Path(tempfile.mktemp(suffix=subtitle.suffix, prefix="animerse_sync_"))
    cmd = [
        "alass",
        str(video),
        str(subtitle),
        str(output),
    ]
    logger.debug("Ejecutando: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error("alass falló (rc=%d): %s", result.returncode, result.stderr)
            output.unlink(missing_ok=True)
            return False

        shutil.move(str(output), str(subtitle))
        return True

    except FileNotFoundError:
        logger.error(
            "alass no encontrado. Descárgalo de: "
            "https://github.com/kaegi/alass/releases "
            "y colócalo en /usr/local/bin/"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("alass excedió el tiempo límite para %s", video.name)
        output.unlink(missing_ok=True)
        return False
    except Exception:
        logger.exception("Error inesperado al ejecutar alass")
        output.unlink(missing_ok=True)
        return False


def sync_subtitle(video: Path, subtitle: Path) -> bool:
    """
    Sincroniza el archivo de subtítulo con el vídeo usando la herramienta
    configurada en ``config.SYNC_TOOL``.

    El subtítulo se sobrescribe in-place con la versión sincronizada.
    Devuelve ``True`` si la sincronización fue exitosa.
    """
    logger.info(
        "Sincronizando subtítulo: %s ↔ %s [backend=%s]",
        subtitle.name, video.name, SYNC_TOOL,
    )

    if SYNC_TOOL == "ffsubsync":
        return _sync_with_ffsubsync(video, subtitle)
    elif SYNC_TOOL == "alass":
        return _sync_with_alass(video, subtitle)
    else:
        logger.error("Herramienta de sincronización desconocida: %s", SYNC_TOOL)
        return False
