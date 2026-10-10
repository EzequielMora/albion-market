"""FASE 0 — Pruebas de viabilidad.

Responde tres preguntas:
  (a) ¿Hay 2 clientes de Albion abiertos en esta PC?
  (b) ¿Cada cuenta recibe los datos del mercado SIN cifrar?
  (c) ¿Pasar de página en el Mercado Negro genera datos nuevos legibles?

Uso (en una terminal COMO ADMINISTRADOR):
    py fase0_prueba.py              # captura hasta Ctrl+C
    py fase0_prueba.py --segundos 120
    py fase0_prueba.py --backend npcap   # si tenés Npcap + scapy instalados
    py fase0_prueba.py --ip 192.168.0.10 # si usás VPN/ExitLag y no detecta la interfaz

Solo escucha el tráfico. No envía nada al juego ni hace clics.
"""
import argparse
import ctypes
import json
import os
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime

from albion_market import capture, procmap
from albion_market.photon import PhotonDecoder, albion_code, iter_strings

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


class Cuenta:
    def __init__(self, pid):
        self.pid = pid
        self.decoder = PhotonDecoder()
        self.paquetes = 0
        self.cifrados = 0
        self.mensajes = Counter()      # tipo -> cantidad
        self.codigos = Counter()       # (tipo, código Albion) -> cantidad
        self.ordenes = Counter()       # "offer"/"request" -> cantidad
        self.ubicaciones = Counter()
        self.lotes_mercado = []        # (hora, cantidad de órdenes, código) para la prueba (c)
        self.ejemplos = []
        self.ids = set()               # Id de orden, para contar únicas


def es_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def resumir(valor, largo=160):
    if isinstance(valor, (bytes, bytearray)):
        return f"<bytes {len(valor)}>"
    if isinstance(valor, list):
        return f"<lista {len(valor)}: {resumir(valor[0], 60) if valor else ''}>"
    if isinstance(valor, dict):
        return f"<dict {len(valor)}>"
    s = repr(valor)
    return s if len(s) <= largo else s[:largo] + "…"


def ordenes_en(msg):
    """Extrae las órdenes de mercado (JSON con UnitPriceSilver) de un mensaje."""
    out = []
    for s in iter_strings(msg.get("params", {})):
        if '"UnitPriceSilver"' in s:
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=int, default=0, help="0 = hasta Ctrl+C")
    ap.add_argument("--backend", choices=["raw", "npcap"], default="raw")
    ap.add_argument("--ip", default=None)
    args = ap.parse_args()

    print("=" * 70)
    print(" FASE 0 — Prueba de viabilidad (solo lectura)")
    print("=" * 70)

    if args.backend == "raw" and not es_admin():
        print("\n[X] Hay que ejecutar esta terminal COMO ADMINISTRADOR (lo exige el socket raw).")
        return

    procesos = procmap.albion_processes()
    print(f"\n(a) Clientes de Albion abiertos: {len(procesos)}")
    for pid, inicio in procesos:
        print(f"    - PID {pid}  (abierto {datetime.fromtimestamp(inicio):%H:%M:%S})")
    if not procesos:
        print("[X] No hay ningún cliente de Albion abierto.")
        return

    cuentas = {pid: Cuenta(pid) for pid, _ in procesos}
    puerto_pid = {}
    sin_dueno = Counter()
    lock = threading.Lock()
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"fase0_{datetime.now():%Y%m%d_%H%M%S}.jsonl")
    log = open(log_path, "w", encoding="utf-8")
    # Paquetes crudos, para poder re-analizar la captura sin repetir la prueba
    crudo = open(log_path.replace(".jsonl", ".crudo.jsonl"), "w", encoding="utf-8")

    def refrescar_puertos():
        puerto_pid.update(procmap.udp_port_to_pid(cuentas.keys()))

    refrescar_puertos()

    def on_packet(sport, dport, payload):
        local = dport if sport in capture.ALBION_PORTS else sport
        entrante = sport in capture.ALBION_PORTS
        pid = puerto_pid.get(local)
        if pid is None:
            sin_dueno[local] += 1
            return
        c = cuentas[pid]
        with lock:
            crudo.write(json.dumps({"t": round(time.time(), 3), "pid": pid,
                                    "dir": "in" if entrante else "out", "hex": payload.hex()}) + "\n")
            c.paquetes += 1
            for msg in c.decoder.feed(payload):
                tipo = msg["type"]
                if tipo == "encrypted":
                    c.cifrados += 1
                    continue
                c.mensajes[tipo] += 1
                if tipo == "error":
                    log.write(json.dumps({"pid": pid, "error": msg["error"], "raw": msg["raw"]}) + "\n")
                    continue
                codigo = albion_code(msg)
                c.codigos[(tipo, codigo)] += 1
                ordenes = ordenes_en(msg) if entrante else []
                if ordenes:
                    calidades = sorted({o.get("QualityLevel") for o in ordenes})
                    encantos = sorted({o.get("EnchantmentLevel") for o in ordenes})
                    c.lotes_mercado.append((time.time(), len(ordenes), codigo, calidades, encantos))
                    for o in ordenes:
                        c.ids.add(o.get("Id"))
                    for o in ordenes:
                        c.ordenes[o.get("AuctionType", "?")] += 1
                        c.ubicaciones[str(o.get("LocationId"))] += 1
                    o = ordenes[0]
                    linea = (f"[PID {pid}] {len(ordenes):>3} órdenes | {o.get('AuctionType')} "
                             f"{o.get('ItemTypeId')} cal={o.get('QualityLevel')} "
                             f"precio={o.get('UnitPriceSilver', 0) / 10000:,.0f} "
                             f"cant={o.get('Amount')} | calidades={calidades} encantos={encantos}")
                    print(linea)
                    if len(c.ejemplos) < 5:
                        c.ejemplos.append(o)
                log.write(json.dumps({
                    "t": round(time.time(), 3), "pid": pid, "dir": "in" if entrante else "out",
                    "tipo": tipo, "codigo_photon": msg["code"], "codigo_albion": codigo,
                    "params": {str(k): resumir(v) for k, v in msg["params"].items()},
                    "ordenes": len(ordenes),
                }, ensure_ascii=False, default=str) + "\n")

    fin = time.time() + args.segundos if args.segundos else None
    stop_flag = threading.Event()

    def stop():
        return stop_flag.is_set() or (fin is not None and time.time() > fin)

    def hilo_puertos():
        while not stop():
            refrescar_puertos()
            time.sleep(3)

    threading.Thread(target=hilo_puertos, daemon=True).start()

    print("\nCapturando... Ahora:")
    print("  1. En cada cuenta abrí el mercado y buscá algún ítem.")
    print("  2. En la cuenta de Caerleon abrí el Mercado Negro (pestaña Vender) y pasá 3-4 páginas.")
    print("  3. Presioná Ctrl+C para terminar y ver el informe.\n")

    try:
        if args.backend == "raw":
            capture.capture_raw(on_packet, ip=args.ip, stop=stop)
        else:
            capture.capture_npcap(on_packet, stop=stop)
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        with lock:
            log.close()
            crudo.close()

    informe(cuentas, sin_dueno, log_path)


def informe(cuentas, sin_dueno, log_path):
    print("\n" + "=" * 70)
    print(" INFORME FASE 0")
    print("=" * 70)
    print(f"\n(a) Clientes detectados: {len(cuentas)} -> "
          f"{'OK' if len(cuentas) >= 2 else 'solo 1 (abrí el segundo cliente y repetí)'}")

    for c in cuentas.values():
        print(f"\n--- Cliente PID {c.pid} ---")
        print(f"  Paquetes capturados : {c.paquetes}")
        print(f"  Mensajes legibles   : {dict(c.mensajes)}")
        print(f"  Mensajes cifrados   : {c.cifrados}")
        total_ord = sum(c.ordenes.values())
        print(f"  Órdenes de mercado  : {total_ord} {dict(c.ordenes)}  lugares={dict(c.ubicaciones)}")
        if c.paquetes == 0:
            veredicto = "SIN TRÁFICO (¿interfaz equivocada? probá --ip o --backend npcap)"
        elif total_ord > 0:
            veredicto = "OK — los datos del mercado se leen SIN cifrar"
        elif c.cifrados > 0:
            veredicto = (f"SIN ÓRDENES y {c.cifrados} mensajes cifrados — si abriste el mercado, "
                         "probablemente llega cifrado")
        else:
            veredicto = "SIN DATOS DE MERCADO (¿abriste el mercado con esta cuenta?)"
        print(f"  (b) Veredicto       : {veredicto}")
        if len(c.lotes_mercado) > 1:
            print(f"  (c) Respuestas de mercado recibidas: {len(c.lotes_mercado)} "
                  f"(una por búsqueda/página) -> "
                  f"{[l[1] for l in c.lotes_mercado][:15]} órdenes c/u")
        print(f"  Órdenes únicas (por Id): {len(c.ids)}")
        mercado = Counter(l[2] for l in c.lotes_mercado)
        if mercado:
            print(f"  Códigos Albion con órdenes: {dict(mercado)}")

    if sin_dueno:
        print(f"\nPaquetes de puertos sin proceso asignado: {sum(sin_dueno.values())} "
              f"(puertos {list(sin_dueno)[:5]})")
    print(f"\nLog detallado: {log_path}")
    print("Mandame este informe (copiá y pegá) para seguir con la fase 1.")


if __name__ == "__main__":
    main()
