"""Decodificador pasivo del protocolo Photon (Protocol18) que usa Albion Online.

Solo lee bytes ya recibidos; nunca envía ni modifica nada.
"""
import struct

# Tipos de mensaje Photon
MSG_REQUEST = 2
MSG_RESPONSE = 3
MSG_EVENT = 4

# Tipos de comando Photon
CMD_RELIABLE = 6
CMD_UNRELIABLE = 7
CMD_FRAGMENT = 8


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError("fin de datos")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def u8(self):
        return self.take(1)[0]

    def varint(self):
        result = shift = 0
        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7
            if shift > 63:
                raise ValueError("varint inválido")

    def zigzag(self):
        n = self.varint()
        return (n >> 1) ^ -(n & 1)

    def string(self):
        return self.take(self.varint()).decode("utf-8", errors="replace")


def _read_value(r, t):
    if t in (0, 8):  # desconocido / null
        return None
    if t == 2:  # bool
        return r.u8() != 0
    if t == 3:
        return r.u8()
    if t == 4:
        return r.unpack("<h")
    if t == 5:
        return r.unpack("<f")
    if t == 6:
        return r.unpack("<d")
    if t == 7:
        return r.string()
    if t in (9, 10):  # int / long comprimidos (zigzag)
        return r.zigzag()
    if t in (11, 15):  # entero de 1 byte positivo
        return r.u8()
    if t in (12, 16):  # entero de 1 byte negativo
        return -r.u8()
    if t in (13, 17):  # entero de 2 bytes positivo
        return r.unpack("<H")
    if t in (14, 18):  # entero de 2 bytes negativo
        return -r.unpack("<H")
    if t == 19:  # custom
        code = r.u8()
        return ("custom", code, r.take(r.varint()))
    if t == 20:
        return _read_dictionary(r)
    if t == 21:  # hashtable
        out = {}
        for _ in range(r.varint()):
            k = _read_value(r, r.u8())
            out[_hashable(k)] = _read_value(r, r.u8())
        return out
    if t == 23:  # array de objetos
        return [_read_value(r, r.u8()) for _ in range(r.varint())]
    if t == 24:
        return _read_request(r)
    if t == 25:
        return _read_response(r)
    if t == 26:
        return _read_event(r)
    if t in (27, 28):  # false / true
        return t == 28
    if 29 <= t <= 34:  # ceros tipados
        return 0
    if t == 64:  # array tipado genérico
        n, et = r.varint(), r.u8()
        return [_read_value(r, et) for _ in range(n)]
    if t == 66:  # array de bool empaquetado en bits
        n = r.varint()
        bits = r.take((n + 7) // 8)
        return [bool(bits[i // 8] >> (i % 8) & 1) for i in range(n)]
    if t == 67:  # array de bytes
        return r.take(r.varint())
    if t == 68:
        return [r.unpack("<h") for _ in range(r.varint())]
    if t == 69:
        return [r.unpack("<f") for _ in range(r.varint())]
    if t == 70:
        return [r.unpack("<d") for _ in range(r.varint())]
    if t == 71:  # array de strings
        return [r.string() for _ in range(r.varint())]
    if t in (73, 74):  # arrays de int / long comprimidos
        return [r.zigzag() for _ in range(r.varint())]
    if t == 83:  # array de custom
        n, code = r.varint(), r.u8()
        return [("custom", code, r.take(r.varint())) for _ in range(n)]
    if t == 84:  # array de diccionarios
        n = r.varint()
        kt, vt = r.u8(), r.u8()
        return [_read_dictionary(r, kt, vt) for _ in range(n)]
    if t == 85:  # array de hashtables
        return [_read_value(r, 21) for _ in range(r.varint())]
    if t >= 0x80:  # custom "slim"
        return ("custom", t & 0x7F, r.take(r.varint()))
    raise ValueError(f"tipo Photon desconocido: {t}")


def _read_dictionary(r, kt=None, vt=None):
    if kt is None:
        kt, vt = r.u8(), r.u8()
    out = {}
    for _ in range(r.varint()):
        k = _read_value(r, r.u8() if kt == 0 else kt)
        out[_hashable(k)] = _read_value(r, r.u8() if vt == 0 else vt)
    return out


def _hashable(k):
    return tuple(k) if isinstance(k, list) else k


def _read_params(r):
    params = {}
    for _ in range(r.u8()):
        key = r.u8()
        params[key] = _read_value(r, r.u8())
    return params


def _read_request(r):
    return {"type": MSG_REQUEST, "code": r.u8(), "params": _read_params(r)}


def _read_response(r):
    code = r.u8()
    ret = r.unpack("<h")
    debug = _read_value(r, r.u8())
    return {"type": MSG_RESPONSE, "code": code, "return": ret, "debug": debug,
            "params": _read_params(r)}


def _read_event(r):
    return {"type": MSG_EVENT, "code": r.u8(), "params": _read_params(r)}


class PhotonDecoder:
    """Decodifica paquetes UDP de un flujo (una cuenta) y reensambla fragmentos.

    `feed(payload)` devuelve una lista de mensajes. Cada mensaje es un dict con
    type/code/params, o {"type": "encrypted"} si llegó cifrado.
    """

    def __init__(self):
        self._fragments = {}

    def feed(self, data):
        out = []
        if len(data) < 12:
            return out
        flags, cmd_count = data[2], data[3]
        if flags == 1:  # paquete completo cifrado
            out.append({"type": "encrypted", "scope": "packet"})
            return out
        off = 12
        for _ in range(cmd_count):
            if off + 12 > len(data):
                break
            ctype, _ch, _cf, _res, clen, _seq = struct.unpack(">BBBBII", data[off:off + 12])
            if clen < 12:
                break
            body = data[off + 12:off + clen]
            off += clen
            if ctype == CMD_RELIABLE:
                self._message(body, out)
            elif ctype == CMD_UNRELIABLE:
                self._message(body[4:], out)
            elif ctype == CMD_FRAGMENT:
                self._fragment(body, out)
        return out

    def _fragment(self, body, out):
        if len(body) < 20:
            return
        start, count, _num, total, frag_off = struct.unpack(">iiiii", body[:20])
        chunk = body[20:]
        if total <= 0 or total > 10_000_000 or frag_off < 0 or frag_off + len(chunk) > total:
            return
        buf, seen = self._fragments.setdefault(start, (bytearray(total), set()))
        buf[frag_off:frag_off + len(chunk)] = chunk
        seen.add(frag_off)
        if len(seen) >= count:
            del self._fragments[start]
            self._message(bytes(buf), out)
        if len(self._fragments) > 200:  # evitar fugas por fragmentos perdidos
            self._fragments.pop(next(iter(self._fragments)))

    @staticmethod
    def _message(body, out):
        if len(body) < 2:
            return
        msg_type = body[1]
        if msg_type & 0x80:
            out.append({"type": "encrypted", "scope": "message"})
            return
        if msg_type not in (MSG_REQUEST, MSG_RESPONSE, MSG_EVENT):
            return
        r = _Reader(body)
        r.pos = 2
        try:
            if msg_type == MSG_REQUEST:
                out.append(_read_request(r))
            elif msg_type == MSG_RESPONSE:
                out.append(_read_response(r))
            else:
                out.append(_read_event(r))
        except (ValueError, struct.error, UnicodeDecodeError) as e:
            out.append({"type": "error", "error": str(e), "raw": body[:64].hex()})


def albion_code(msg):
    """Albion guarda el código real de operación en el parámetro 253 (y el de evento en 252)."""
    p = msg.get("params", {})
    if msg["type"] == MSG_EVENT:
        return p.get(252, msg["code"])
    return p.get(253, msg["code"])


def iter_strings(value):
    """Recorre recursivamente un valor decodificado y devuelve todos sus strings."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from iter_strings(v)
