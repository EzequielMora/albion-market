"""Base de datos local (SQLite) con todo lo que se captura."""
import os
import sqlite3
import time

from . import rutas

DB_PATH = os.path.join(rutas.DATA, "mercado.db")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ordenes_mn (
    id INTEGER PRIMARY KEY, item_id TEXT, tier INTEGER, encantamiento INTEGER,
    calidad INTEGER, precio INTEGER, cantidad INTEGER, visto REAL
);
CREATE TABLE IF NOT EXISTS ofertas_ciudad (
    id INTEGER PRIMARY KEY, item_id TEXT, tier INTEGER, encantamiento INTEGER,
    calidad INTEGER, precio INTEGER, cantidad INTEGER, ciudad TEXT, visto REAL
);
CREATE INDEX IF NOT EXISTS ix_mn_item ON ordenes_mn(item_id);
CREATE INDEX IF NOT EXISTS ix_of_item ON ofertas_ciudad(item_id);
"""


class Store:
    def __init__(self, path=DB_PATH):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(_ESQUEMA)

    def guardar_mn(self, ordenes):
        """Inserta/actualiza órdenes del Mercado Negro. Devuelve cuántas eran nuevas."""
        if not ordenes:
            return 0
        ahora = time.time()
        ids = [o.id for o in ordenes]
        existentes = {r[0] for r in self.db.execute(
            f"SELECT id FROM ordenes_mn WHERE id IN ({','.join('?' * len(ids))})", ids)}
        self.db.executemany(
            "INSERT INTO ordenes_mn VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "precio=excluded.precio, cantidad=excluded.cantidad, visto=excluded.visto",
            [(o.id, o.item_id, o.tier, o.encantamiento, o.calidad, o.precio, o.cantidad, ahora)
             for o in ordenes])
        self.db.commit()
        return len(set(ids) - existentes)

    def guardar_ofertas(self, ordenes, ciudad=None):
        ahora = time.time()
        self.db.executemany(
            "INSERT INTO ofertas_ciudad VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "precio=excluded.precio, cantidad=excluded.cantidad, visto=excluded.visto",
            [(o.id, o.item_id, o.tier, o.encantamiento, o.calidad, o.precio, o.cantidad, ciudad, ahora)
             for o in ordenes])
        self.db.commit()

    def ordenes_mn(self, max_edad_seg=None):
        sql = "SELECT id, item_id, tier, encantamiento, calidad, precio, cantidad, visto FROM ordenes_mn"
        args = ()
        if max_edad_seg:
            sql += " WHERE visto >= ?"
            args = (time.time() - max_edad_seg,)
        return self.db.execute(sql, args).fetchall()

    def contar(self):
        mn = self.db.execute("SELECT COUNT(*) FROM ordenes_mn").fetchone()[0]
        of = self.db.execute("SELECT COUNT(*) FROM ofertas_ciudad").fetchone()[0]
        return mn, of
