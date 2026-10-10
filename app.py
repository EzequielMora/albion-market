"""Albion Market — versión de consola (la gráfica es gui.py).

ETAPA 1 (en Caerleon): abrí el Mercado Negro (pestaña Vender) y pasá páginas.
ETAPA 2 (en la ciudad): Ctrl+V + Enter en el buscador del mercado; el siguiente nombre se copia solo.

Uso (terminal COMO ADMINISTRADOR):  py app.py
La app solo escucha el tráfico y escribe en el portapapeles. Nunca toca el juego.
"""
import ctypes
import os
import queue
import sys
import threading
import time

from albion_market import procmap, sonido
from albion_market.catalog import CALIDADES, Catalogo
from albion_market.sesion import Sesion, cargar_config, ultimo_escaneo
from albion_market.sniffer import Sniffer
from albion_market.store import Store


def es_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def m(n):
    return f"{n:,}".replace(",", ".")


def hace(segundos):
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"hace {minutos} min"
    if minutos < 60 * 24:
        return f"hace {minutos // 60} h {minutos % 60} min"
    return f"hace {minutos // (60 * 24)} días"


class Consola:
    def __init__(self):
        self.cat = Catalogo()
        self.sesion = Sesion(self.cat, cargar_config(), Store(), self.evento)
        self.lock = threading.Lock()   # la sesión se usa desde el hilo de red y desde el teclado

    def linea(self, op):
        o = op.objetivo
        return (f"{self.cat.etiqueta(op.item_id)} | comprá {CALIDADES[op.calidad]} a {m(op.precio_compra)}"
                f" → MN paga {m(o.precio)} ({CALIDADES[o.calidad]}+) | +{m(op.ganancia)} "
                f"(+{op.porcentaje:.1f}%) | x{op.unidades}")

    def evento(self, tipo, **d):
        if tipo == "silver":
            print(f"   💰 Silver: {m(d['cantidad'])}")
        elif tipo == "mn":
            print(f"   [MN] +{d['nuevas']} órdenes ({m(d['minimo'])} – {m(d['maximo'])}) → "
                  f"{d['total']} guardadas")
        elif tipo == "nombre":
            g = d["grupo"]
            if d["cambio_bloque"]:
                sonido.cambio_bloque()
                print("\n" + "=" * 60)
                print(f"   🔧 PONÉ LOS FILTROS →  TIER: {g.tier}   ENCANTAMIENTO: {g.encantamiento}")
                print("=" * 60)
            print(f"📋 ({d['indice'] + 1}/{d['total']}) {g.nombre} {g.bloque}  "
                  f"[{len(g.objetivos)} órdenes, hasta {m(g.mejor_precio)}]  · quedan {d['faltan_bloque']} en {g.bloque}")
        elif tipo == "filtro_mal":
            sonido.error()
            print(f"   ⚠️  El filtro de {d['campo']} está en {d['puesto']}: ponelo en {d['esperado']} "
                  f"y repetí Ctrl+V, Enter.")
        elif tipo == "oportunidad":
            sonido.oportunidad()
            print("   🔔 " + self.linea(d["op"]))
        elif tipo == "recopiado":
            print(f"   ↺ Esa búsqueda no era la de la lista: volví a copiar «{d['grupo'].nombre}»")
        elif tipo == "salto":
            print(f"⏭️  Bloque {d['bloque']} saltado ({d['saltados']} nombres sin buscar).")
        elif tipo == "fin":
            print("\n✅ Terminaste la lista. Escribí 'l' para ver las oportunidades o 'q' para salir.")

    def on_dato(self, pid, dato):
        with self.lock:
            self.sesion.procesar(pid, dato)

    def elegir_bloques(self):
        bloques = self.sesion.bloques()
        print("\nNombres a buscar por tier.encantamiento:")
        for bloque, n, mejor in bloques:
            print(f"   {bloque}: {n:>3} nombres (órdenes hasta {m(mejor)})")
        validos = {b for b, _, _ in bloques}
        while True:
            elegidos = input("¿Qué bloques vas a barrer? (ej: 6.1 6.2 7.3 · Enter = todos): ").replace(",", " ").split()
            invalidos = [b for b in elegidos if b not in validos]
            if not invalidos:
                return set(elegidos) or None
            print(f"   No hay órdenes para: {', '.join(invalidos)}. Elegí de la lista.")

    def lista(self):
        with self.lock:
            ops = self.sesion.oportunidades()
            print(f"\n=== OPORTUNIDADES ({len(ops)}) — mayor % primero ===")
            for i, op in enumerate(ops, 1):
                print(f"{i:>3}. {self.linea(op)}")
            if ops:
                r = self.sesion.resumen(ops)
                print(f"\nTOTAL: invertís {m(r['inversion'])} → ganás {m(r['ganancia'])} "
                      f"(+{r['porcentaje']:.1f}%) en {r['items']} ítems")
                silver = self.sesion.motor.silver
                if silver is not None and r["inversion"] > silver:
                    print(f"⚠️  Tu silver ({m(silver)}) no alcanza para todo: empezá por las de arriba (mayor %).")
            if self.sesion.revisar_luego:
                print(f"\nPodrían tener más en la página 2 ({len(self.sesion.revisar_luego)}): "
                      f"{', '.join(self.sesion.revisar_luego)}")
            print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not es_admin():
        print("[X] Ejecutá esta terminal COMO ADMINISTRADOR.")
        return
    if not procmap.albion_processes():
        print("[X] Abrí Albion Online primero.")
        return

    print("Cargando catálogo...")
    app = Consola()
    c = app.sesion.cfg
    print(f"Config: impuesto {c.impuesto_venta:.0%} · ganancia mín {m(c.ganancia_min)} · "
          f"{c.porcentaje_min}% mín · órdenes MN desde {m(c.precio_mn_min)}  (editable en config.json)")

    sniffer = Sniffer(app.on_dato)
    threading.Thread(target=sniffer.correr, daemon=True).start()

    print("\n=== ETAPA 1: MERCADO NEGRO ===")
    print("Abrí el Mercado Negro (pestaña Vender) y pasá todas las páginas que quieras.")
    ruta, datos = ultimo_escaneo()
    if ruta:
        print(f"Último escaneo guardado: {os.path.basename(ruta)} — {len(datos['ordenes'])} órdenes, "
              f"{hace(time.time() - datos['fecha'])}.")
    resp = input("Cuando termines presioná Enter (o escribí 'u' + Enter para usar el último escaneo guardado):\n")
    with app.lock:
        if resp.strip().lower() == "u":
            usado = app.sesion.reutilizar_escaneo()
            if usado:
                ruta, datos = usado
                print(f"Usando {os.path.basename(ruta)}: {len(datos['ordenes'])} órdenes "
                      f"({hace(time.time() - datos['fecha'])}).")
            else:
                print("No hay escaneos guardados todavía: se usa solo lo escaneado ahora.")
        elif app.sesion.escaneo:
            print(f"Escaneo guardado en escaneos/{os.path.basename(app.sesion.escaneo_path)}")
    bloques = app.elegir_bloques()

    print("\n=== ETAPA 2: CIUDAD ===")
    print("En el buscador del mercado: Ctrl+V, Enter. Repetí.")
    print("Comandos aquí: [Enter] saltar al siguiente bloque · s = saltar nombre · "
          "r = recopiar · l = lista · q = salir\n")
    with app.lock:
        app.sesion.iniciar_barrido(bloques)

    acciones = {"": "saltar_bloque", "s": "saltar_nombre", "r": "recopiar"}
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "q":
                break
            if cmd == "l":
                app.lista()
            elif cmd in acciones:
                with app.lock:
                    getattr(app.sesion, acciones[cmd])()
    except (KeyboardInterrupt, EOFError):
        pass
    sniffer.detener()
    app.lista()


if __name__ == "__main__":
    main()
