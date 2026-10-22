"""Carpeta base de Orbi.

- Corriendo con Python normal: la carpeta donde están los .py (igual que antes).
- Convertido a .exe (PyInstaller): la carpeta donde está Orbi.exe. Ahí viven tu .env, config.json,
  orbi_profile.json, models/, etc. (NO dentro del paquete, porque ahí se pierden o son de solo lectura).
"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
