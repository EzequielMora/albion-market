"""Convierte mensajes Photon de Albion en datos de mercado.

Códigos confirmados en la fase 0 (2026-10-09):
- Operación 81: órdenes de venta del mercado normal (pestaña Comprar)
- Operación 82: órdenes de compra del Mercado Negro (pestaña Vender)
- Operación 83: compra directa de una oferta (solo informativo)
- Evento 81:   silver del jugador (parámetro 1, ×10000)
"""
import json
from dataclasses import dataclass

from .photon import MSG_EVENT, MSG_REQUEST, MSG_RESPONSE, albion_code

OP_OFERTAS = 81
OP_PEDIDOS_MN = 82
EV_SILVER = 81
ESCALA = 10000


@dataclass
class Orden:
    id: int
    item_id: str
    tier: int
    encantamiento: int
    calidad: int
    precio: int          # silver por unidad
    cantidad: int
    tipo: str            # "offer" (venta en ciudad) / "request" (compra, ej. Mercado Negro)
    comprador: str | None

    @property
    def es_mercado_negro(self):
        return self.comprador == "@BLACK_MARKET"


@dataclass
class Pagina:
    """Una respuesta de mercado (50 órdenes como máximo) con los filtros que la pidieron."""
    operacion: int
    ordenes: list
    filtros: dict
    offset: int | None   # None si la respuesta llegó sin solicitud (el juego a veces repite páginas)


@dataclass
class Silver:
    cantidad: int


def _orden(texto):
    o = json.loads(texto)
    return Orden(
        id=o["Id"], item_id=o["ItemTypeId"], tier=o.get("Tier"),
        encantamiento=o.get("EnchantmentLevel", 0), calidad=o.get("QualityLevel", 1),
        precio=o["UnitPriceSilver"] // ESCALA, cantidad=o.get("Amount", 1),
        tipo=o.get("AuctionType"), comprador=o.get("BuyerName"),
    )


def _filtros(params):
    """Filtros de la solicitud 81/82: categoría, subcategoría, tier, encantamiento, índices de ítems."""
    return {
        "categoria": params.get(1) or None,
        "subcategoria": params.get(2) or None,
        "tier": params.get(7) or None,
        "encantamiento": params.get(10) if params.get(10) not in ("", None) else None,
        "indices": params.get(8),
    }


class Interprete:
    """Uno por cuenta. Relaciona cada respuesta con su solicitud (parámetro 255)."""

    def __init__(self):
        self._solicitudes = {}

    def procesar(self, msg):
        tipo = msg.get("type")
        if tipo not in (MSG_REQUEST, MSG_RESPONSE, MSG_EVENT):
            return None
        codigo = albion_code(msg)
        p = msg["params"]

        if tipo == MSG_EVENT:
            if codigo == EV_SILVER and isinstance(p.get(1), int):
                return Silver(p[1] // ESCALA)
            return None

        if codigo not in (OP_OFERTAS, OP_PEDIDOS_MN):
            return None
        if tipo == MSG_REQUEST:
            self._solicitudes[(codigo, p.get(255))] = p
            if len(self._solicitudes) > 100:
                self._solicitudes.pop(next(iter(self._solicitudes)))
            return None

        solicitud = self._solicitudes.pop((codigo, p.get(255)), {})
        ordenes = []
        for texto in p.get(0) or []:
            try:
                ordenes.append(_orden(texto))
            except (ValueError, KeyError, TypeError):
                continue
        offset = (solicitud.get(13) or 0) if solicitud else None
        return Pagina(codigo, ordenes, _filtros(solicitud), offset)
