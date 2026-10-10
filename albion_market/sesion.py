"""Lógica de una sesión de flipping Ciudad → Mercado Negro (sin interfaz).

La usan la app gráfica (gui.py) y la de consola (app.py). Avisa lo que pasa llamando a
on_evento(tipo, **datos):

  "silver"       cantidad
  "mn"           nuevas, total, minimo, maximo        (página del Mercado Negro capturada)
  "nombre"       grupo, indice, total, faltan_bloque, hechos_bloque, total_bloque, cambio_bloque
  "filtro_mal"   campo, puesto, esperado
  "oportunidad"  op
  "ciudad"                                             (llegó una página de la ciudad)
  "salto"        bloque, saltados
  "recopiado"    grupo, ok          (llegó una búsqueda que no era la de la lista: se volvió a copiar)
  "fin"

No es thread-safe: llamar todo desde un mismo hilo.
"""
import glob
import json
import os
import time
from datetime import datetime

from . import clipboard, rutas
from .engine import Config, Motor, Objetivo
from .market import OP_OFERTAS, OP_PEDIDOS_MN, Pagina, Silver


def cargar_config():
    if not os.path.exists(rutas.CONFIG):
        guardar_config(Config())
    with open(rutas.CONFIG, encoding="utf-8") as f:
        return Config.desde_dict(json.load(f))


def guardar_config(cfg):
    with open(rutas.CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg.__dict__, f, indent=2)


def ultimo_escaneo(excluir=None):
    """(ruta, datos) del escaneo del MN guardado más reciente, o (None, None)."""
    rutas_mn = sorted(p for p in glob.glob(os.path.join(rutas.ESCANEOS, "mn_*.json")) if p != excluir)
    if not rutas_mn:
        return None, None
    with open(rutas_mn[-1], encoding="utf-8") as f:
        return rutas_mn[-1], json.load(f)


class Sesion:
    def __init__(self, catalogo, cfg, store, on_evento):
        self.cat = catalogo
        self.cfg = cfg
        self.store = store
        self.emitir = on_evento
        self.motor = Motor(catalogo, cfg)
        self.etapa = 1
        self.grupos = []
        self.actual = 0                 # índice del grupo cuyo nombre está en el portapapeles
        self.revisar_luego = []
        self.avisadas = set()
        self.escaneo = {}               # órdenes del MN capturadas en ESTA sesión (id -> dict)
        self.escaneo_path = os.path.join(rutas.ESCANEOS, f"mn_{datetime.now():%Y%m%d_%H%M%S}.json")

    # --- datos de red -----------------------------------------------------
    def procesar(self, pid, dato):
        if isinstance(dato, Silver):
            self.motor.silver = dato.cantidad
            self.emitir("silver", cantidad=dato.cantidad)
        elif isinstance(dato, Pagina) and dato.operacion == OP_PEDIDOS_MN and self.etapa == 1:
            self._pagina_mn(dato)
        elif isinstance(dato, Pagina) and dato.operacion == OP_OFERTAS and self.etapa == 2:
            self._pagina_ciudad(dato)

    def _pagina_mn(self, pag):
        mn = [o for o in pag.ordenes if o.es_mercado_negro]
        if not mn:
            return
        self.store.guardar_mn(mn)
        self.motor.cargar_objetivos(mn)
        self._guardar_escaneo(mn)
        precios = [o.precio for o in mn]
        self.emitir("mn", nuevas=len(mn), total=len(self.escaneo), minimo=min(precios), maximo=max(precios))

    def _items_completos(self, pag):
        """Ítems cuya lista de ofertas vino entera en esta página (primera página y no llena),
        respetando los filtros de tier/encantamiento que se usaron."""
        if pag.offset != 0 or len(pag.ordenes) >= 50 or not pag.filtros.get("indices"):
            return []
        tier, ench = pag.filtros.get("tier"), pag.filtros.get("encantamiento")
        items = []
        for indice in pag.filtros["indices"]:
            item_id = self.cat.por_indice.get(indice)
            it = self.cat.get(item_id) if item_id else None
            if not it:
                continue
            if tier not in (None, "") and str(it["tier"]) != str(tier):
                continue
            if ench not in (None, "") and str(it["encantamiento"]) != str(ench):
                continue
            items.append(item_id)
        return items

    def _pagina_ciudad(self, pag):
        self.store.guardar_ofertas(pag.ordenes)
        self.motor.cargar_ofertas(pag.ordenes, reemplazar=self._items_completos(pag))
        self._avisar_nuevas()
        self.emitir("ciudad")

        if self.actual >= len(self.grupos):
            return
        grupo = self.grupos[self.actual]
        pedidos = set(pag.filtros.get("indices") or [])
        if not pedidos & self.motor.indices(grupo):
            # Resultado de otra búsqueda (una repetida, o un nombre copiado a mano para comprar):
            # se aprovecha pero no avanza, y se vuelve a poner en el portapapeles el nombre que toca.
            ok = clipboard.copiar(grupo.nombre)
            self.emitir("recopiado", grupo=grupo, ok=ok)
            return
        for campo, esperado in (("tier", grupo.tier), ("encantamiento", grupo.encantamiento)):
            puesto = pag.filtros.get(campo)
            if puesto not in (None, "") and str(puesto) != str(esperado):
                self.emitir("filtro_mal", campo=campo, puesto=puesto, esperado=esperado)
                return
        if self.motor.hay_que_seguir(grupo, pag.ordenes):
            self.revisar_luego.append(f"{grupo.nombre} {grupo.bloque}")
        self.actual += 1
        self._copiar_actual()

    def _avisar_nuevas(self):
        for op in self.motor.oportunidades():
            clave = (op.objetivo.id, op.precio_compra)
            if clave not in self.avisadas:
                self.avisadas.add(clave)
                self.emitir("oportunidad", op=op)

    def _copiar_actual(self):
        if self.actual >= len(self.grupos):
            self.emitir("fin")
            return
        g = self.grupos[self.actual]
        anterior = self.grupos[self.actual - 1] if self.actual > 0 else None
        copiado = clipboard.copiar(g.nombre)
        del_bloque = [x for x in self.grupos if x.bloque == g.bloque]
        faltan = sum(1 for x in self.grupos[self.actual:] if x.bloque == g.bloque)
        self.emitir("nombre", grupo=g, indice=self.actual, total=len(self.grupos),
                    faltan_bloque=faltan, total_bloque=len(del_bloque),
                    hechos_bloque=len(del_bloque) - faltan,
                    cambio_bloque=anterior is None or anterior.bloque != g.bloque, copiado=copiado)

    # --- escaneos del Mercado Negro ---------------------------------------
    def _guardar_escaneo(self, ordenes):
        """Reescribe el archivo de ESTE escaneo con cada página (no se pierde nada si se cierra)."""
        for o in ordenes:
            self.escaneo[o.id] = {"id": o.id, "item_id": o.item_id, "calidad": o.calidad,
                                  "precio": o.precio, "cantidad": o.cantidad}
        os.makedirs(rutas.ESCANEOS, exist_ok=True)
        with open(self.escaneo_path, "w", encoding="utf-8") as f:
            json.dump({"fecha": time.time(), "ordenes": list(self.escaneo.values())}, f)

    def ultimo_escaneo_previo(self):
        return ultimo_escaneo(excluir=self.escaneo_path)

    def reutilizar_escaneo(self):
        """Carga el último escaneo guardado (anterior a esta sesión). Devuelve (ruta, datos) o None."""
        ruta, datos = self.ultimo_escaneo_previo()
        if not ruta:
            return None
        for o in datos["ordenes"]:
            if o["precio"] >= self.cfg.precio_mn_min:
                self.motor.objetivos[o["id"]] = Objetivo(o["id"], o["item_id"], o["calidad"],
                                                         o["precio"], o["cantidad"])
        return ruta, datos

    # --- barrido de la ciudad ---------------------------------------------
    def bloques(self):
        """[(bloque, cantidad de nombres, orden MN más cara)] de 8.4 hacia abajo."""
        conteo = {}
        for g in self.motor.grupos():
            conteo.setdefault(g.bloque, []).append(g)
        return [(b, len(gs), max(g.mejor_precio for g in gs)) for b, gs in conteo.items()]

    def iniciar_barrido(self, bloques=None):
        self.grupos = [g for g in self.motor.grupos() if bloques is None or g.bloque in bloques]
        self.etapa = 2
        self.actual = 0
        self._copiar_actual()

    def saltar_nombre(self):
        if self.actual < len(self.grupos):
            self.actual += 1
            self._copiar_actual()

    def saltar_bloque(self):
        if self.actual >= len(self.grupos):
            return
        bloque = self.grupos[self.actual].bloque
        saltados = 0
        while self.actual < len(self.grupos) and self.grupos[self.actual].bloque == bloque:
            self.actual += 1
            saltados += 1
        self.emitir("salto", bloque=bloque, saltados=saltados)
        self._copiar_actual()

    def recopiar(self):
        self._copiar_actual()

    def oportunidades(self):
        return self.motor.oportunidades()

    def resumen(self, ops=None):
        ops = self.oportunidades() if ops is None else ops
        inversion = sum(op.precio_compra * op.unidades for op in ops)
        ganancia = sum(op.ganancia * op.unidades for op in ops)
        return {"inversion": inversion, "ganancia": ganancia,
                "porcentaje": 100 * ganancia / inversion if inversion else 0.0,
                "items": sum(op.unidades for op in ops)}
