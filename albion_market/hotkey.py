"""Tecla global (p. ej. F8) que funciona aunque estés dentro del juego.

Usa RegisterHotKey de Windows: la app solo ESCUCHA esa tecla; no envía nada al juego.
"""
import ctypes
import threading
from ctypes import wintypes

_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def codigo_tecla(nombre):
    """'F8' -> código virtual de Windows. Solo teclas F1–F24."""
    nombre = nombre.strip().upper()
    if nombre.startswith("F") and nombre[1:].isdigit() and 1 <= int(nombre[1:]) <= 24:
        return 0x6F + int(nombre[1:])
    raise ValueError(f"Tecla no válida: {nombre} (usá F1 a F24)")


def escuchar(nombre_tecla, callback):
    """Llama callback() (desde otro hilo) cada vez que se presiona la tecla.

    Devuelve True si se pudo registrar (False si otra app ya usa esa tecla).
    """
    vk = codigo_tecla(nombre_tecla)
    listo = threading.Event()
    ok = []

    def bucle():
        ok.append(bool(_user32.RegisterHotKey(None, 1, _MOD_NOREPEAT, vk)))
        listo.set()
        if not ok[0]:
            return
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY:
                callback()

    threading.Thread(target=bucle, daemon=True).start()
    listo.wait(2)
    return bool(ok and ok[0])
