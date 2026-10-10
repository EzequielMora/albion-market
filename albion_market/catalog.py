"""Catálogo de ítems: ID interno → nombre en español, tier, encantamiento y categoría.

Fuente: ao-data/ao-bin-dumps (formatted/items.json + items.xml) en data/.
La primera carga genera data/catalogo.json, mucho más rápido de leer.
"""
import json
import os
import re

from . import rutas

DATA_DIR = rutas.DATA
CACHE = os.path.join(DATA_DIR, "catalogo.json")
CACHE_EMPAQUETADO = os.path.join(rutas.RECURSOS, "data", "catalogo.json")  # dentro del .exe

CALIDADES = {1: "Normal", 2: "Buena", 3: "Notable", 4: "Sobresaliente", 5: "Obra maestra"}

_XML_ITEM = re.compile(r'<\w+ uniquename="([^"]+)"([^>]*)>')
_ATTR = re.compile(r'(shopcategory|shopsubcategory1|tier)="([^"]*)"')


def _construir():
    with open(os.path.join(DATA_DIR, "items.json"), encoding="utf-8") as f:
        items = json.load(f)
    categorias = {}
    with open(os.path.join(DATA_DIR, "items.xml"), encoding="utf-8") as f:
        for m in _XML_ITEM.finditer(f.read()):
            attrs = dict(_ATTR.findall(m.group(2)))
            if "shopcategory" in attrs:
                categorias.setdefault(m.group(1), attrs)

    catalogo = {}
    for it in items:
        uid = it["UniqueName"]
        base, _, ench = uid.partition("@")
        attrs = categorias.get(base, {})
        tier = re.match(r"T(\d)_", uid)
        catalogo[uid] = {
            "indice": int(it["Index"]),
            "nombre": (it.get("LocalizedNames") or {}).get("ES-ES") or uid,
            "tier": int(tier.group(1)) if tier else None,
            "encantamiento": int(ench) if ench.isdigit() else 0,
            "categoria": attrs.get("shopcategory"),
            "subcategoria": attrs.get("shopsubcategory1"),
        }
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False)
    return catalogo


class Catalogo:
    def __init__(self):
        fuentes = [os.path.join(DATA_DIR, n) for n in ("items.json", "items.xml")]
        hay_fuentes = all(os.path.exists(p) for p in fuentes)
        if hay_fuentes and (not os.path.exists(CACHE) or
                            any(os.path.getmtime(p) > os.path.getmtime(CACHE) for p in fuentes)):
            self.items = _construir()
        else:
            ruta = CACHE if os.path.exists(CACHE) else CACHE_EMPAQUETADO
            with open(ruta, encoding="utf-8") as f:
                self.items = json.load(f)
        self.por_indice = {v["indice"]: k for k, v in self.items.items()}

    def get(self, item_id):
        return self.items.get(item_id)

    def nombre(self, item_id):
        it = self.items.get(item_id)
        return it["nombre"] if it else item_id

    def etiqueta(self, item_id, calidad=None):
        """'Garras del anciano 8.4 (Buena)'"""
        it = self.items.get(item_id)
        if not it:
            return item_id
        txt = f"{it['nombre']} {it['tier']}.{it['encantamiento']}"
        if calidad:
            txt += f" ({CALIDADES.get(calidad, calidad)})"
        return txt
