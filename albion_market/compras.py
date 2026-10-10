"""Compras marcadas a mano: lo que compraste para venderle al Mercado Negro y su historial.

Se guarda en compras.json junto a la app.
"""
import json
import os
import time
from datetime import datetime

from . import rutas

RUTA = os.path.join(rutas.BASE, "compras.json")


class Compras:
    def __init__(self, ruta=RUTA):
        self.ruta = ruta
        self.items = []
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                self.items = json.load(f)

    def _guardar(self):
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)

    def _buscar(self, rid):
        return next((r for r in self.items if r["id"] == rid), None)

    def agregar(self, op, nombre, impuesto):
        o = op.objetivo
        rec = {
            "id": f"{time.time():.6f}",
            "estado": "comprado",
            "fecha_compra": time.time(),
            "item_id": op.item_id,
            "nombre": nombre,
            "calidad": op.calidad,
            "unidades": op.unidades,
            "precio_compra": op.precio_compra,      # por unidad
            "orden_mn": o.id,
            "id_oferta": op.id_oferta,
            "mn_precio": o.precio,                  # lo que paga la orden del MN, por unidad
            "mn_calidad": o.calidad,
            "impuesto": impuesto,
            "ganancia_esperada": op.ganancia * op.unidades,
        }
        self.items.append(rec)
        self._guardar()
        return rec

    def vender(self, rid, precio_venta):
        """Marca como vendido. `precio_venta` es por unidad, antes del impuesto."""
        r = self._buscar(rid)
        if not r:
            return None
        neto = int(precio_venta * (1 - r["impuesto"]))
        r.update(estado="vendido", fecha_venta=time.time(), precio_venta=precio_venta,
                 ganancia_real=(neto - r["precio_compra"]) * r["unidades"])
        self._guardar()
        return r

    def deshacer(self, rid):
        """Borra la compra (vuelve a aparecer como oportunidad si la oferta sigue)."""
        r = self._buscar(rid)
        if r:
            self.items.remove(r)
            self._guardar()
        return r

    def pendientes(self):
        return [r for r in self.items if r["estado"] == "comprado"]

    def vendidos(self):
        return sorted((r for r in self.items if r["estado"] == "vendido"),
                      key=lambda r: r["fecha_venta"], reverse=True)

    def reservados(self):
        """Órdenes del MN que ya tenés cubiertas con algo comprado."""
        return {r["orden_mn"] for r in self.pendientes()}

    def resumen(self):
        hoy = datetime.now().date()
        vendidos = self.vendidos()
        pend = self.pendientes()
        return {
            "invertido": sum(r["precio_compra"] * r["unidades"] for r in pend),
            "esperado": sum(r["ganancia_esperada"] for r in pend),
            "hoy": sum(r["ganancia_real"] for r in vendidos
                       if datetime.fromtimestamp(r["fecha_venta"]).date() == hoy),
            "total": sum(r["ganancia_real"] for r in vendidos),
            "ventas": len(vendidos),
        }
