# 🦊 AniMerse

Pipeline automatizado para servidores Jellyfin headless.  
Organiza archivos de anime, descarga subtítulos japoneses desde Jimaku/Kitsunekko, y subtítulos en español e inglés mediante `subliminal`, para luego sincronizarlos con el vídeo.

---

## Requisitos del Sistema

| Componente | Versión mínima |
|---|---|
| Ubuntu | 24.04 LTS |
| Python | 3.10+ |
| ffmpeg | cualquiera (requerido por ffsubsync) |
| unrar | cualquiera (solo si Kitsunekko devuelve .rar) |

---

## Instalación

### 1. Dependencias del sistema

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg unrar
```

### 2. Clonar / copiar el proyecto

```bash
# Copiar los archivos al servidor (o clonar tu repo)
mkdir -p ~/AniMerse && cd ~/AniMerse
# ... colocar aquí los archivos del proyecto ...
```

### 3. Ejecutar script de inicio (Entorno virtual + API Key)

El proyecto incluye un script `run.sh` que creará automáticamente el entorno virtual, instalará las dependencias necesarias y configurará tu API Key de Jimaku para descargar los subtítulos.

```bash
cd ~/AniMerse
chmod +x run.sh
./run.sh
```

### 4. (Opcional) Instalar `alass` como backend de sincronización

Si prefieres `alass` en lugar de `ffsubsync`:

```bash
# Descargar el binario desde GitHub
wget https://github.com/kaegi/alass/releases/latest/download/alass-linux64 -O alass
chmod +x alass
sudo mv alass /usr/local/bin/
```

### 5. Crear las carpetas necesarias

```bash
mkdir -p ~/Downloads/Anime     # Carpeta de origen (donde llegan los vídeos)
mkdir -p ~/Jellyfin/Series     # Raíz de la biblioteca Jellyfin
```

---

## Uso

### Ejecución básica

Para ejecutar el programa con todos los ajustes predeterminados, simplemente ejecuta tu script de inicio:

```bash
cd ~/AniMerse
./run.sh
```

Esto escanea `~/Downloads/Anime`, organiza los vídeos en `~/Jellyfin/Series/`, descarga subtítulos japoneses (priorizando archivos .srt y buscando coincidir grupos) y los sincroniza con `ffsubsync`.

### Opciones de línea de comandos

```
python animerse.py [opciones]

  --source, -s PATH       Carpeta de origen (defecto: ~/Downloads/Anime)
  --sync-tool TOOL        ffsubsync | alass (defecto: ffsubsync)
  --skip-subs             No descargar subtítulos
  --skip-sync             No sincronizar subtítulos
  --dry-run               Solo analizar nombres, sin mover archivos
  -v, --verbose           Activar logging detallado
```

### Ejemplos

Cualquier argumento adicional que pases a `run.sh` se le enviará directamente a `animerse.py`:

```bash
# Usar una carpeta de origen diferente
./run.sh --source /mnt/descargas/anime

# Solo organizar archivos, sin subtítulos ni sincronización
./run.sh --skip-subs --skip-sync

# Sincronizar con alass en vez de ffsubsync
./run.sh --sync-tool alass

# Ver qué haría el script sin mover nada
./run.sh --dry-run -v
```

### Variables de entorno (alternativa a CLI)

| Variable | Descripción | Valor por defecto |
|---|---|---|
| `ANIMERSE_SOURCE` | Carpeta de origen | `~/Downloads/Anime` |
| `ANIMERSE_DEST` | Raíz Jellyfin | `~/Jellyfin/Series` |
| `ANIMERSE_SYNC_TOOL` | `ffsubsync` o `alass` | `ffsubsync` |
| `ANIMERSE_LOG` | Ruta del archivo de log | `~/animerse.log` |
| `ANIMERSE_LOG_LEVEL` | Nivel de log | `INFO` |

---

## Estructura de salida

```
~/Jellyfin/Series/
├── Jujutsu Kaisen (2020)/
│   └── Season 01/
│       ├── Jujutsu Kaisen - S01E01.mkv
│       ├── Jujutsu Kaisen - S01E01.ja.ass
│       ├── Jujutsu Kaisen - S01E01.es.srt
│       ├── Jujutsu Kaisen - S01E01.en.srt
│       ├── Jujutsu Kaisen - S01E02.mkv
│       └── Jujutsu Kaisen - S01E02.ja.srt
├── Frieren Beyond Journey's End/
│   └── Season 01/
│       ├── Frieren Beyond Journey's End - S01E01.mkv
│       └── Frieren Beyond Journey's End - S01E01.ja.ass
...
```

---

## Formatos de nombre soportados

El parser reconoce los patrones más comunes de los grupos fansub:

| Patrón de entrada | Detección |
|---|---|
| `[SubGroup] Anime Name - 05 (1080p) [HASH].mkv` | ✅ Anime Name, Ep 05 |
| `Anime Name S02E10.mkv` | ✅ Anime Name, S02E10 |
| `[Group] Anime Name (2023) - 05.mkv` | ✅ Anime Name, Año 2023, Ep 05 |
| `Anime.Name.-.12.(720p).mkv` | ✅ Anime Name, Ep 12 |
| `Anime Name - Episode 07.mkv` | ✅ Anime Name, Ep 07 |
| `Anime Name E07.mkv` | ✅ Anime Name, Ep 07 |

---

## Automatización con cron

Para ejecutar AniMerse automáticamente cada hora:

```bash
crontab -e
```

Añadir:

```cron
0 * * * * /home/TU_USUARIO/AniMerse/run.sh >> /tmp/animerse_cron.log 2>&1
```

---

## Arquitectura del código

```
AniMerse/
├── animerse.py        # Script principal (punto de entrada)
├── config.py          # Configuración centralizada
├── parser.py          # Parser de nombres de archivo de anime
├── organizer.py       # Renombrado y estructura de carpetas Jellyfin
├── subtitles.py       # Scraper de Kitsunekko + extracción de archivos
├── sync.py            # Sincronización de subtítulos (ffsubsync/alass)
└── requirements.txt   # Dependencias Python
```

| Módulo | Responsabilidad |
|---|---|
| `config.py` | Rutas, URLs, constantes. Sin lógica. |
| `parser.py` | Regex para extraer nombre, episodio, temporada, año. |
| `organizer.py` | `shutil.move` + creación de carpetas Jellyfin. |
| `subtitles.py` | HTTP scraping (Jimaku/Kitsunekko), descargas vía `subliminal` (es/en) y manejo de .zip/.rar. |
| `sync.py` | Wrapper de `subprocess` para ffsubsync/alass. |
| `animerse.py` | Orquestación del pipeline, CLI y logging. |

---

## Solución de problemas

| Problema | Solución |
|---|---|
| `ffsubsync: command not found` | `pip install ffsubsync` dentro del venv |
| `alass: command not found` | Descargar binario y mover a `/usr/local/bin/` |
| `No se encontró carpeta en Kitsunekko` | El nombre del anime puede diferir; revisar manualmente en kitsunekko.net |
| `rarfile` import error | `pip install rarfile` + `sudo apt install unrar` |
| Subtítulo no sincronizado correctamente | Probar con `--sync-tool alass` como alternativa |
| Nombre de archivo no reconocido | Usar `--dry-run -v` para diagnosticar el parsing |

---

## Licencia

Proyecto personal. Uso libre.
