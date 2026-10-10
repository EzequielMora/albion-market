"""Identifica a qué cliente de Albion (proceso) pertenece cada puerto UDP local."""
import psutil

ALBION_EXE = "albion-online.exe"


def albion_processes():
    """Lista de (pid, hora de inicio) de los clientes de Albion abiertos."""
    out = []
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        if (p.info["name"] or "").lower() == ALBION_EXE:
            out.append((p.info["pid"], p.info["create_time"]))
    return sorted(out, key=lambda x: x[1])


def udp_port_to_pid(pids):
    """{puerto_local: pid} para los sockets UDP de los procesos indicados."""
    pids = set(pids)
    mapping = {}
    for c in psutil.net_connections(kind="udp"):
        if c.pid in pids and c.laddr:
            mapping[c.laddr.port] = c.pid
    return mapping
