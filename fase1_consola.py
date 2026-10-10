"""FASE 1 — Capturador en consola.

Muestra y guarda en data/mercado.db lo que cada cuenta ve:
  - Cuenta BM:        órdenes de compra del Mercado Negro (con nombre en español)
  - Cuenta principal: ofertas de la ciudad y el silver del jugador

Uso (terminal COMO ADMINISTRADOR):
    py fase1_consola.py
    py fase1_consola.py --reproducir logs/xxx.crudo.jsonl   # probar con una captura grabada

Solo escucha el tráfico. No envía nada al juego ni hace clics.
"""
import argparse
import ctypes
import sys
from datetime import datetime

from albion_market import procmap
from albion_market.catalog import Catalogo
from albion_market.market import OP_OFERTAS, OP_PEDIDOS_MN, Pagina, Silver
from albion_market.sniffer import Sniffer
from albion_market.store import Store


def es_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elegir_roles(procesos):
    """Pregunta qué cliente es BM y cuál es el principal. Con 1 cliente, cumple ambos roles."""
    if len(procesos) == 1:
        pid = procesos[0][0]
        print(f"Un solo cliente abierto (PID {pid}): se usa para BM y principal a la vez.")
        return pid, pid
    print("Clientes de Albion abiertos:")
    for i, (pid, inicio) in enumerate(procesos, 1):
        print(f"  {i}. PID {pid} (abierto {datetime.fromtimestamp(inicio):%H:%M:%S})")
    print("Tip: el primero que abriste aparece arriba.")
    while True:
        try:
            bm = int(input("¿Número del cliente que escanea el MERCADO NEGRO? "))
            pr = int(input("¿Número del cliente PRINCIPAL (ciudad)? "))
            if bm != pr and 1 <= bm <= len(procesos) and 1 <= pr <= len(procesos):
                return procesos[bm - 1][0], procesos[pr - 1][0]
        except ValueError:
            pass
        print("Elegí dos números distintos de la lista.")


def pagina(dato):
    return "?" if dato.offset is None else dato.offset // 50 + 1


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reproducir", help="captura cruda .crudo.jsonl")
    ap.add_argument("--backend", choices=["raw", "npcap"], default="raw")
    ap.add_argument("--ip")
    args = ap.parse_args()

    print("Cargando catálogo de ítems...")
    cat = Catalogo()
    store = Store(":memory:") if args.reproducir else Store()  # reproducir no ensucia la base real

    if args.reproducir:
        pid_bm = pid_pr = None  # en reproducción se acepta cualquier PID para ambos roles
    else:
        if args.backend == "raw" and not es_admin():
            print("[X] Ejecutá esta terminal COMO ADMINISTRADOR.")
            return
        procesos = procmap.albion_processes()
        if not procesos:
            print("[X] No hay ningún cliente de Albion abierto.")
            return
        pid_bm, pid_pr = elegir_roles(procesos)

    def on_dato(pid, dato):
        if isinstance(dato, Silver):
            if pid_pr in (None, pid):
                print(f"[PRINCIPAL] 💰 Silver: {dato.cantidad:,}")
            return
        if not isinstance(dato, Pagina) or not dato.ordenes:
            return
        if dato.operacion == OP_PEDIDOS_MN and pid_bm in (None, pid):
            nuevas = store.guardar_mn(dato.ordenes)
            total, _ = store.contar()
            print(f"\n[BM] Página {pagina(dato)}: {len(dato.ordenes)} órdenes "
                  f"({nuevas} nuevas, {total} guardadas en total)")
            for o in dato.ordenes[:5]:
                print(f"     {cat.etiqueta(o.item_id, o.calidad):<55} paga {o.precio:>13,}  x{o.cantidad}")
            if len(dato.ordenes) > 5:
                print(f"     ... y {len(dato.ordenes) - 5} más")
        elif dato.operacion == OP_OFERTAS and pid_pr in (None, pid):
            store.guardar_ofertas(dato.ordenes)
            f = dato.filtros
            filtro = " · ".join(str(x) for x in (f["categoria"], f["subcategoria"],
                                                 f["tier"] and f"T{f['tier']}",
                                                 f["encantamiento"] is not None and f"enc {f['encantamiento']}")
                                if x)
            precios = [o.precio for o in dato.ordenes]
            print(f"\n[PRINCIPAL] Página {pagina(dato)} [{filtro or 'búsqueda por nombre'}]: "
                  f"{len(dato.ordenes)} ofertas, de {min(precios):,} a {max(precios):,}")
            vistos = set()
            for o in dato.ordenes:
                if (o.item_id, o.calidad) in vistos:
                    continue
                vistos.add((o.item_id, o.calidad))
                if len(vistos) > 5:
                    break
                print(f"     {cat.etiqueta(o.item_id, o.calidad):<55} vende {o.precio:>13,}  x{o.cantidad}")

    sniffer = Sniffer(on_dato, backend=args.backend, ip=args.ip)
    if args.reproducir:
        sniffer.reproducir(args.reproducir)
        return
    print("\nEscuchando... (Ctrl+C para salir)")
    try:
        sniffer.correr()
    except KeyboardInterrupt:
        sniffer.detener()
    mn, of = store.contar()
    print(f"\nGuardado en data/mercado.db: {mn} órdenes del Mercado Negro, {of} ofertas de ciudad.")


if __name__ == "__main__":
    main()
