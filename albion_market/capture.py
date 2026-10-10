"""Captura pasiva del tráfico UDP de Albion Online.

Backends:
- "raw": socket raw de Windows (SIO_RCVALL). No requiere instalar nada, pero sí
  ejecutar como administrador.
- "npcap": scapy + Npcap, si están instalados. Más fiable.

Solo escucha: nunca envía ni modifica paquetes.
"""
import socket
import struct

ALBION_PORTS = (5055, 5056, 5058)


def local_ip():
    """IP de la interfaz que sale a internet (no envía nada: UDP connect solo elige ruta)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _parse_ipv4_udp(pkt):
    """Devuelve (src_port, dst_port, payload) si es UDP de Albion, si no None."""
    if len(pkt) < 20 or pkt[0] >> 4 != 4 or pkt[9] != 17:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    if len(pkt) < ihl + 8:
        return None
    sport, dport, ulen = struct.unpack(">HHH", pkt[ihl:ihl + 6])
    if sport not in ALBION_PORTS and dport not in ALBION_PORTS:
        return None
    return sport, dport, pkt[ihl + 8:ihl + ulen]


def capture_raw(callback, ip=None, stop=lambda: False):
    """Llama callback(src_port, dst_port, payload) por cada paquete UDP de Albion."""
    ip = ip or local_ip()
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
    s.bind((ip, 0))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
    s.settimeout(1.0)
    try:
        while not stop():
            try:
                pkt = s.recv(65535)
            except socket.timeout:
                continue
            parsed = _parse_ipv4_udp(pkt)
            if parsed:
                callback(*parsed)
    finally:
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        s.close()


def capture_npcap(callback, stop=lambda: False):
    from scapy.all import sniff, UDP  # import diferido: scapy es opcional

    flt = " or ".join(f"udp port {p}" for p in ALBION_PORTS)

    def on_pkt(p):
        if UDP in p:
            callback(p[UDP].sport, p[UDP].dport, bytes(p[UDP].payload))

    while not stop():
        sniff(filter=flt, prn=on_pkt, store=False, timeout=1)
