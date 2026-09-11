#!/usr/bin/env bash

# Cambiar al directorio del script
cd "$(dirname "$0")" || exit

# Crear el entorno virtual si no existe
if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv .venv
fi

# Activar el entorno virtual (usamos la versión bash/sh genérica)
source .venv/bin/activate

# Instalar dependencias
echo "Instalando dependencias..."
pip install -r requirements.txt

# Configurar la API Key de Jimaku
export ANIMERSE_JIMAKU_API_KEY="AAAAAAAAPF4uAS4NO6SXTHA-cVe8vdYuxyBM4EjvLkUBlobyvG_Je63rNQ"

# Ejecutar el script principal pasando los argumentos que se reciban
echo "Iniciando AniMerse..."
python3 animerse.py "$@"
