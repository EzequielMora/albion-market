"""Copia texto al portapapeles de Windows (Unicode, con tildes y ñ).

Solo escribe en el portapapeles del sistema; no toca la ventana del juego.
"""
import ctypes
import time
from ctypes import wintypes

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k32.GlobalAlloc.restype = wintypes.HGLOBAL
_k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_k32.GlobalLock.restype = wintypes.LPVOID
_k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_u32.SetClipboardData.restype = wintypes.HANDLE


def copiar(texto):
    """Devuelve True si se copió. Reintenta si otro programa (p. ej. el juego) tiene el portapapeles."""
    data = (texto + "\0").encode("utf-16-le")
    for _ in range(25):
        if _u32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        _u32.EmptyClipboard()
        h = _k32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
        ptr = _k32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        _k32.GlobalUnlock(h)
        return bool(_u32.SetClipboardData(_CF_UNICODETEXT, h))
    finally:
        _u32.CloseClipboard()
