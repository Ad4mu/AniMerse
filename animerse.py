#!/usr/bin/env python3
"""
animerse.py — Pipeline principal de AniMerse.

Ejecuta secuencialmente los tres pasos del flujo:
  1. Organizar archivos de vídeo en la estructura Jellyfin.
  2. Descargar subtítulos japoneses desde Kitsunekko.
  3. Sincronizar subtítulos con el audio del vídeo.

Uso:
    python animerse.py [--source /ruta/origen] [--sync-tool ffsubsync|alass]
                       [--skip-subs] [--skip-sync] [--dry-run] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import config
from organizer import scan_and_organize
from subtitles import download_subtitle
from sync import sync_subtitle


def _setup_logging(verbose: bool = False) -> None:
    """Configura logging a consola y archivo."""
    level = logging.DEBUG if verbose else getattr(logging, config.LOG_LEVEL, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        handlers.append(fh)
    except OSError as exc:
        print(f"⚠  No se pudo crear el archivo de log: {exc}", file=sys.stderr)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="animerse",
        description="AniMerse — Organiza anime, descarga subs JP y sincroniza.",
    )
    parser.add_argument(
        "--source", "-s",
        type=Path,
        default=None,
        help="Carpeta de origen con los vídeos descargados "
             f"(por defecto: {config.SOURCE_DIR})",
    )
    parser.add_argument(
        "--sync-tool",
        choices=["ffsubsync", "alass"],
        default=None,
        help=f"Herramienta de sincronización (por defecto: {config.SYNC_TOOL})",
    )
    parser.add_argument(
        "--sub-provider",
        choices=["jimaku", "kitsunekko", "all"],
        default=None,
        help=f"Proveedor de subtítulos (por defecto: {config.SUBTITLE_PROVIDER})",
    )
    parser.add_argument(
        "--skip-subs",
        action="store_true",
        help="Omitir la descarga de subtítulos.",
    )
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Omitir la sincronización de subtítulos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo analizar nombres, no mover archivos.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Activar logging de depuración.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _setup_logging(verbose=args.verbose)
    logger = logging.getLogger("animerse")

    if args.sync_tool:
        config.SYNC_TOOL = args.sync_tool
    if args.sub_provider:
        config.SUBTITLE_PROVIDER = args.sub_provider

    source = args.source or config.SOURCE_DIR

    logger.info("=" * 60)
    logger.info("AniMerse — inicio del pipeline")
    logger.info("Origen: %s", source)
    logger.info("Destino: %s", config.JELLYFIN_ROOT)
    logger.info("Sub provider: %s", config.SUBTITLE_PROVIDER)
    logger.info("Sync tool: %s", config.SYNC_TOOL)
    logger.info("=" * 60)

    # ── Paso 1: Organización ──────────────────────────────────────────────
    if args.dry_run:
        logger.info("[DRY-RUN] Analizando archivos sin moverlos…")
        from parser import parse_filename
        for f in sorted(source.iterdir()):
            if f.is_file():
                info = parse_filename(f)
                if info:
                    logger.info(
                        "  %s → %s S%02dE%02d (año=%s)",
                        f.name, info.anime_name, info.season, info.episode, info.year,
                    )
                else:
                    logger.warning("  %s → ⚠ no reconocido", f.name)
        return

    episodes = scan_and_organize(source)
    if not episodes:
        logger.warning("No se encontraron episodios para procesar.")
        return

    # ── Paso 2: Descarga de subtítulos ────────────────────────────────────
    subtitle_map: dict[int, Path] = {}  # episode_index → subtitle_path
    if not args.skip_subs:
        for idx, ep in enumerate(episodes):
            try:
                sub_path = download_subtitle(ep)
                if sub_path:
                    subtitle_map[idx] = sub_path
            except Exception:
                logger.exception(
                    "Error al descargar subtítulo para %s E%02d",
                    ep.anime_name, ep.episode,
                )
    else:
        logger.info("Descarga de subtítulos omitida (--skip-subs).")

    # ── Paso 3: Sincronización ────────────────────────────────────────────
    if not args.skip_sync and subtitle_map:
        for idx, sub_path in subtitle_map.items():
            ep = episodes[idx]
            try:
                ok = sync_subtitle(ep.original_path, sub_path)
                if ok:
                    logger.info(
                        "✔ Subtítulo sincronizado: %s", sub_path.name
                    )
                else:
                    logger.warning(
                        "⚠ Sincronización fallida: %s (se conserva el original)",
                        sub_path.name,
                    )
            except Exception:
                logger.exception(
                    "Error al sincronizar %s", sub_path.name
                )
    elif args.skip_sync:
        logger.info("Sincronización omitida (--skip-sync).")

    # ── Resumen ───────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Resumen:")
    logger.info("  Episodios organizados:  %d", len(episodes))
    logger.info("  Subtítulos descargados: %d", len(subtitle_map))
    synced = sum(1 for _ in subtitle_map)  # todos los que llegaron al paso 3
    logger.info("  Subtítulos procesados:  %d", synced)
    logger.info("Pipeline completado.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
