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
                # pyrefly: ignore [missing-import]
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

    # Ordenar archivos para priorizar .srt y consistencia de grupo (fansub)
    video_filename = info.original_path.name
    group_match = re.match(r'^\[(.*?)\]', video_filename)
    video_group = group_match.group(1).lower() if group_match else ""

    def sort_key(f: SubtitleFile):
        ext = Path(f.filename).suffix.lower()
        score = 0
        
        # Prioridad 1: Coincidencia de grupo (Fansub) en el nombre
        if video_group and f"[{video_group}]" in f.filename.lower():
            score += 100
            
        # Prioridad 2: Priorizar .srt para evitar transcodificación / compatibilidad en TV
        if ext == '.srt':
            score += 10
        elif ext == '.ass':
            score += 5
        elif ext in ARCHIVE_EXTENSIONS:
            score += 1
            
        # Retornar score invertido para orden descendente, luego nombre para orden alfabético consistente
        return (-score, f.filename)

    files.sort(key=sort_key)

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
# Limpieza de subtítulos bilingües
# ---------------------------------------------------------------------------

def _clean_bilingual_ass(filepath: Path) -> None:
    """
    Lee un archivo .ass y, si contiene estilos separados para japonés y 
    otros idiomas (ej. inglés/romaji), elimina las líneas de diálogo 
    que no pertenezcan a los estilos japoneses.
    """
    if filepath.suffix.lower() != ".ass":
        return
    
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='utf-16') as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning("No se pudo leer el subtítulo %s para limpieza: %s", filepath.name, e)
            return
            
    style_has_japanese = {}
    # Patrón para caracteres hiragana, katakana y kanji
    japanese_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]')
    
    for line in lines:
        if line.startswith('Dialogue:'):
            parts = line.split(',', 9)
            if len(parts) >= 10:
                style = parts[3]
                text = parts[9]
                
                # Quitar etiquetas ASS para evaluar solo el texto visible
                text_clean = re.sub(r'\{.*?\}', '', text)
                
                if style not in style_has_japanese:
                    style_has_japanese[style] = False
                
                if not style_has_japanese[style]:
                    if japanese_pattern.search(text_clean):
                        style_has_japanese[style] = True
                        
    # Si no hay texto japonés en absoluto o si todos los estilos tienen japonés, no hacemos nada
    if not any(style_has_japanese.values()) or all(style_has_japanese.values()):
        return
        
    new_lines = []
    removed_styles = [s for s, has_jp in style_has_japanese.items() if not has_jp]
    logger.info("Eliminando pista(s) no japonesa(s) del subtítulo: %s", ", ".join(removed_styles))
    
    for line in lines:
        if line.startswith('Dialogue:'):
            parts = line.split(',', 9)
            if len(parts) >= 10:
                style = parts[3]
                if not style_has_japanese.get(style, True):
                    continue
        new_lines.append(line)
        
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning("Error al guardar el subtítulo limpio %s: %s", filepath.name, e)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def download_subtitle(info: EpisodeInfo) -> list[Path]:
    """
    Busca, descarga y renombra subtítulos para el episodio dado.
    Utiliza los proveedores configurados para japonés y subliminal para español e inglés.

    Devuelve una lista con las rutas a los archivos de subtítulo finales (ya renombrados junto
    al vídeo).
    """
    downloaded_paths: list[Path] = []
    video_dir = info.original_path.parent

    logger.info(
        "Buscando subtítulos para: %s S%02dE%02d",
        info.anime_name, info.season, info.episode,
    )

    # 1. Subtítulos Japoneses (vía proveedores configurados)
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
        logger.error("No hay proveedores activos para japonés: %s", SUBTITLE_PROVIDER)
    else:
        subtitle_path_ja: Optional[Path] = None
        for provider in active_providers:
            logger.info("Intentando con proveedor japonés: %s", provider.name)
            subtitle_path_ja = _try_download_from_provider(provider, info)
            if subtitle_path_ja:
                logger.info("✔ Subtítulo japonés encontrado con %s", provider.name)
                break
            else:
                logger.info("✘ Falló con %s", provider.name)

        if subtitle_path_ja:
            _clean_bilingual_ass(subtitle_path_ja)
            sub_ext = subtitle_path_ja.suffix
            final_name_ja = f"{info.original_path.stem}.ja{sub_ext}"
            final_path_ja = video_dir / final_name_ja
            shutil.move(str(subtitle_path_ja), str(final_path_ja))
            logger.info("Subtítulo japonés guardado: %s", final_path_ja.name)
            downloaded_paths.append(final_path_ja)
        else:
            logger.warning("Ningún proveedor pudo encontrar subtítulo japonés para %s E%02d", info.anime_name, info.episode)

    # 2. Subtítulos adicionales (Español, Inglés) vía subliminal
    try:
        import subliminal
        from babelfish import Language
        from subliminal.video import Episode as SubliminalEpisode

        logger.info("Buscando subtítulos adicionales (es, en) con subliminal...")
        video = SubliminalEpisode(
            info.original_path.name,
            info.anime_name,
            info.season,
            info.episode
        )
        
        langs = {Language('spa'), Language('eng')}
        subs = subliminal.download_best_subtitles([video], langs)
        
        for sub in subs.get(video, []):
            try:
                lang_code = sub.language.alpha2  # 'es' or 'en'
                # Subliminal typically downloads .srt
                final_name = f"{info.original_path.stem}.{lang_code}.srt"
                final_path = video_dir / final_name
                
                with open(final_path, "wb") as f:
                    f.write(sub.content)
                
                logger.info("✔ Subtítulo %s guardado: %s", lang_code, final_path.name)
                downloaded_paths.append(final_path)
            except Exception as e:
                logger.warning("Error al guardar subtítulo %s de subliminal: %s", sub.language.alpha2, e)
                
    except ImportError:
        logger.warning("La librería 'subliminal' no está instalada. No se descargarán subtítulos extra.")
    except Exception as e:
        logger.exception("Error al buscar subtítulos con subliminal: %s", e)

    return downloaded_paths
