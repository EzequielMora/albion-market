"""Motor de cálculo: cruza objetivos del Mercado Negro con ofertas de la ciudad.

Regla de calidad: la oferta de la ciudad sirve si tiene el MISMO ítem (tier.encantamiento)
y calidad IGUAL O SUPERIOR a la que pide la orden del Mercado Negro.
"""
import time
from dataclasses import dataclass, field


@dataclass
class Config:
    impuesto_venta: float = 0.08      # sin premium; vender a una orden del MN paga solo este impuesto
    ganancia_min: int = 50_000        # silver netos mínimos por unidad
    porcentaje_min: float = 10.0      # % mínimo de ganancia
    precio_mn_min: int = 200_000      # ignorar órdenes del MN que pagan menos que esto
    tecla_saltar_bloque: str = "F8"   # tecla global (desde el juego) para saltar el bloque actual

    @classmethod
    def desde_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Objetivo:
    """Una orden de compra del Mercado Negro."""
    id: int
    item_id: str
    calidad: int
    precio: int
    cantidad: int

    def neto(self, cfg):
        return int(self.precio * (1 - cfg.impuesto_venta))


@dataclass
class Oportunidad:
    objetivo: Objetivo
    item_id: str
    calidad: int          # calidad de la oferta que se compra
    precio_compra: int
    disponibles: int
    ganancia: int
    porcentaje: float
    unidades: int         # cuántas conviene comprar (orden MN, oferta y silver)
    visto: float = 0.0    # cuándo se vio la oferta en la ciudad (time.time())
    id_oferta: int = 0


@dataclass
class Grupo:
    """Objetivos que se cubren con una búsqueda: nombre + filtros de tier y encantamiento."""
    nombre: str
    tier: int
    encantamiento: int
    item_ids: set = field(default_factory=set)
    objetivos: list = field(default_factory=list)

    @property
    def bloque(self):
        """'7.3': lo que hay que poner en los filtros de tier y encantamiento."""
        return f"{self.tier}.{self.encantamiento}"

    @property
    def mejor_precio(self):
        return max(o.precio for o in self.objetivos)


class Motor:
    def __init__(self, catalogo, cfg):
        self.cat = catalogo
        self.cfg = cfg
        self.objetivos = {}     # id -> Objetivo
        self.ofertas = {}       # item_id -> {id_oferta: (calidad, precio, cantidad, visto)}
        self.silver = None
        self.reservados = set()        # órdenes del MN que ya vas a llenar con algo comprado
        self.excluir_ofertas = set()   # ofertas compradas o descartadas

    # --- carga de datos -------------------------------------------------
    def cargar_objetivos(self, ordenes):
        for o in ordenes:
            if o.precio >= self.cfg.precio_mn_min:
                self.objetivos[o.id] = Objetivo(o.id, o.item_id, o.calidad, o.precio, o.cantidad)

    def cargar_ofertas(self, ordenes, reemplazar=()):
        """Guarda una página de ofertas.

        `reemplazar`: ítems cuya lista de ofertas llegó COMPLETA en esta página; lo que se había
        visto antes de ellos se borra (si una oferta ya no aparece, alguien la compró).
        """
        ahora = time.time()
        for item_id in reemplazar:
            self.ofertas.pop(item_id, None)
        for o in ordenes:
            self.ofertas.setdefault(o.item_id, {})[o.id] = (o.calidad, o.precio, o.cantidad, ahora)

    # --- grupos de búsqueda ---------------------------------------------
    def grupos(self):
        """Objetivos agrupados por (nombre, tier, encantamiento).

        Sin filtro de encantamiento la primera página se llena de versiones .0 baratas,
        así que se ordena en bloques tier.encantamiento (8.4, 8.3, …, 7.4, …): el usuario
        cambia los filtros una vez por bloque y dentro del bloque va del objetivo más caro
        al más barato.
        """
        por_clave = {}
        for obj in self.objetivos.values():
            it = self.cat.get(obj.item_id) or {}
            clave = (self.cat.nombre(obj.item_id), it.get("tier") or 0, it.get("encantamiento", 0))
            g = por_clave.setdefault(clave, Grupo(*clave))
            g.item_ids.add(obj.item_id)
            g.objetivos.append(obj)
        return sorted(por_clave.values(), key=lambda g: (-g.tier, -g.encantamiento, -g.mejor_precio))

    def indices(self, grupo):
        return {self.cat.get(i)["indice"] for i in grupo.item_ids if self.cat.get(i)}

    # --- cálculo ----------------------------------------------------------
    def oportunidades(self):
        """Asigna ofertas de la ciudad a órdenes del MN sin usar una oferta dos veces.

        Se arman todos los pares (orden MN, oferta) rentables y se reparten de mayor a menor %:
        cada oferta se consume según su cantidad y cada orden según las unidades que pide.
        """
        pares = []
        for obj in self.objetivos.values():
            if obj.id in self.reservados:
                continue
            neto = obj.neto(self.cfg)
            for id_oferta, (calidad, precio, cantidad, visto) in self.ofertas.get(obj.item_id, {}).items():
                if calidad < obj.calidad or not precio or id_oferta in self.excluir_ofertas:
                    continue
                if self.silver is not None and precio > self.silver:
                    continue
                ganancia = neto - precio
                porcentaje = 100 * ganancia / precio
                if ganancia >= self.cfg.ganancia_min and porcentaje >= self.cfg.porcentaje_min:
                    pares.append((porcentaje, ganancia, obj, id_oferta, calidad, precio, cantidad, visto))
        pares.sort(key=lambda p: (p[0], p[1]), reverse=True)

        quedan_oferta, quedan_orden, ops = {}, {}, []
        for porcentaje, ganancia, obj, id_oferta, calidad, precio, cantidad, visto in pares:
            unidades = min(quedan_oferta.get(id_oferta, cantidad), quedan_orden.get(obj.id, obj.cantidad))
            if self.silver is not None:
                unidades = min(unidades, self.silver // precio)  # no sugerir más de lo que alcanza
            if unidades <= 0:
                continue
            quedan_oferta[id_oferta] = quedan_oferta.get(id_oferta, cantidad) - unidades
            quedan_orden[obj.id] = quedan_orden.get(obj.id, obj.cantidad) - unidades
            ops.append(Oportunidad(obj, obj.item_id, calidad, precio, cantidad,
                                   ganancia, porcentaje, unidades, visto, id_oferta))
        return ops

    def hay_que_seguir(self, grupo, pagina_ordenes):
        """Regla de corte: ¿vale la pena pasar a la página siguiente de esta búsqueda?

        Las ofertas vienen de menor a mayor precio. Si la página no está llena, no hay más.
        Si el precio más alto de la página ya supera lo máximo que se puede pagar
        (ingreso neto del objetivo más caro, o el silver), las siguientes tampoco sirven.
        """
        if len(pagina_ordenes) < 50:
            return False
        tope = max(o.neto(self.cfg) for o in grupo.objetivos) - self.cfg.ganancia_min
        if self.silver is not None:
            tope = min(tope, self.silver)
        return max(o.precio for o in pagina_ordenes) < tope
