"""Rutas de archivos, iguales corriendo con Python o como .exe (PyInstaller)."""
import os
import sys

CONGELADO = getattr(sys, "frozen", False)

# Carpeta escribible (config, base de datos, escaneos, logs): junto al .exe o la raíz del proyecto
BASE = (os.path.dirname(sys.executable) if CONGELADO
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Recursos de solo lectura empaquetados dentro del .exe (catálogo)
RECURSOS = getattr(sys, "_MEIPASS", BASE)

DATA = os.path.join(BASE, "data")
ESCANEOS = os.path.join(BASE, "escaneos")
LOGS = os.path.join(BASE, "logs")
CONFIG = os.path.join(BASE, "config.json")
