"""Sonidos suaves (onda senoidal con entrada y caída suaves), sin bloquear la app.

Se generan como .wav una sola vez en la carpeta temporal y se reproducen en segundo plano.
"""
import math
import os
import struct
import tempfile
import wave
import winsound

_RATE = 44100
_DIR = os.path.join(tempfile.gettempdir(), "albion_market_sonidos")

# nombre -> lista de (frecuencia Hz, duración ms), volumen 0..1
_SONIDOS = {
    "oportunidad": ([(880, 220)], 0.22),             # un pip tranquilo
    "cambio_bloque": ([(587, 160), (440, 260)], 0.28),
    "error": ([(220, 380)], 0.30),
}


def _generar(nombre, notas, volumen):
    ruta = os.path.join(_DIR, f"{nombre}.wav")
    muestras = []
    for frecuencia, ms in notas:
        n = int(_RATE * ms / 1000)
        ataque = int(_RATE * 0.012)
        for i in range(n):
            t = i / _RATE
            env = min(1.0, i / ataque) * math.exp(-4.0 * i / n)  # entra suave y se apaga
            muestras.append(volumen * env * math.sin(2 * math.pi * frecuencia * t))
        muestras.extend([0.0] * int(_RATE * 0.03))  # pequeña pausa entre notas
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in muestras))
    return ruta


def _ruta(nombre):
    ruta = os.path.join(_DIR, f"{nombre}.wav")
    if not os.path.exists(ruta):
        os.makedirs(_DIR, exist_ok=True)
        notas, volumen = _SONIDOS[nombre]
        _generar(nombre, notas, volumen)
    return ruta


def _tocar(nombre):
    try:
        winsound.PlaySound(_ruta(nombre),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (RuntimeError, OSError):
        pass


def oportunidad():
    """Pip tranquilo: apareció una ganga."""
    _tocar("oportunidad")


def cambio_bloque():
    """Dos notas descendentes: hay que cambiar los filtros de tier/encantamiento."""
    _tocar("cambio_bloque")


def error():
    """Nota grave: filtro equivocado."""
    _tocar("error")
