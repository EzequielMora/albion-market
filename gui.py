"""Albion Market — app gráfica (Ciudad → Mercado Negro).

Solo escucha el tráfico del juego y escribe en el portapapeles. Nunca toca el juego.
Requiere ejecutarse como administrador (el .exe lo pide solo).
"""
import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import customtkinter as ctk

from albion_market import clipboard, hotkey, procmap, rutas, sonido
from albion_market.compras import Compras
from albion_market.catalog import CALIDADES, Catalogo
from albion_market.sesion import Sesion, cargar_config, guardar_config
from albion_market.sniffer import Sniffer
from albion_market.store import Store

# --- paleta -------------------------------------------------------------
BG = "#121418"
CARD = "#1b1e24"
CARD2 = "#22262e"
BORDE = "#2c313a"
TEXTO = "#e9e7e2"
TENUE = "#8a909b"
ORO = "#e2b553"
ORO_OSC = "#b98d32"
VERDE = "#4fbf85"
ROJO = "#e26464"
NARANJA = "#e99a4a"
FUENTE = "Segoe UI"


def m(n):
    return f"{n:,}".replace(",", ".")


def hace(segundos):
    if segundos < 60:
        return "ahora"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"hace {minutos} min"
    if minutos < 60 * 24:
        return f"hace {minutos // 60} h {minutos % 60} min"
    return f"hace {minutos // (60 * 24)} días"


ESTADO = os.path.join(rutas.BASE, "estado.json")  # último silver conocido


def leer_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_estado(**datos):
    estado = leer_estado()
    estado.update(datos)
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f)


def es_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def F(size, bold=False):
    return ctk.CTkFont(family=FUENTE, size=size, weight="bold" if bold else "normal")


class Tarjeta(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDE)
        super().__init__(master, **kw)


def boton(master, texto, comando, primario=False, **kw):
    if primario:
        kw.setdefault("fg_color", ORO)
        kw.setdefault("hover_color", ORO_OSC)
        kw.setdefault("text_color", "#16130b")
    else:
        kw.setdefault("fg_color", CARD2)
        kw.setdefault("hover_color", BORDE)
        kw.setdefault("text_color", TEXTO)
    kw.setdefault("height", 38)
    kw.setdefault("corner_radius", 10)
    return ctk.CTkButton(master, text=texto, command=comando, font=F(13, primario), **kw)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Albion Market · Ciudad → Mercado Negro")
        self.geometry("1260x760")
        self.minsize(980, 600)
        self.after(0, lambda: self.state("zoomed"))  # maximizada: entra en cualquier pantalla
        self.configure(fg_color=BG)

        self.cola = queue.Queue()
        self.cat = Catalogo()
        self.cfg = cargar_config()
        self.store = Store()
        self.compras = Compras()
        estado = leer_estado()
        self.silver_conocido = estado.get("silver")
        self.silver_fecha = estado.get("fecha")
        self.sesion = self._nueva_sesion()
        self.tabla_sucia = False
        self.ultimo_refresco = 0.0
        self.vars_bloques = {}

        self._estilo_tabla()
        self._construir()
        self._mostrar("mn")
        self._iniciar_sniffer()
        self._iniciar_tecla()
        self._mostrar_silver()
        self._refrescar_compras()
        self.bind("<Return>", lambda _e: self._enter())
        self.after(40, self._drenar)
        self.after(500, self._chequear_albion)
        self.after(300, self._poner_icono)  # customtkinter pone su ícono al arrancar; se reemplaza después

    def _poner_icono(self):
        icono = os.path.join(rutas.RECURSOS, "assets", "icono.ico")
        if os.path.exists(icono):
            self.iconbitmap(icono)

    def _nueva_sesion(self):
        sesion = Sesion(self.cat, self.cfg, self.store, self._evento)
        sesion.motor.silver = self.silver_conocido
        sesion.motor.reservados = self.compras.reservados()
        sesion.motor.excluir_ofertas = {r.get("id_oferta") for r in self.compras.pendientes()}
        return sesion

    # =====================================================================
    # Construcción de la interfaz
    # =====================================================================
    def _estilo_tabla(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.layout("Op.Treeview", [("Op.Treeview.treearea", {"sticky": "nswe"})])  # sin borde blanco
        st.configure("Op.Treeview", background=CARD2, fieldbackground=CARD2, foreground=TEXTO,
                     rowheight=30, borderwidth=0, font=(FUENTE, 10))
        st.configure("Op.Treeview.Heading", background=CARD, foreground=TENUE, relief="flat",
                     font=(FUENTE, 10, "bold"), padding=(6, 6))
        st.map("Op.Treeview", background=[("selected", "#3a3220")], foreground=[("selected", ORO)])
        st.map("Op.Treeview.Heading", background=[("active", CARD2)])
        st.configure("Op.Vertical.TScrollbar", background=CARD2, troughcolor=CARD, borderwidth=0,
                     arrowcolor=TENUE)

    def _construir(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- cabecera ---
        cab = ctk.CTkFrame(self, fg_color="transparent")
        cab.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(16, 8))
        cab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(cab, text="Albion Market", font=F(24, True), text_color=TEXTO).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(cab, text="   Ciudad → Mercado Negro", font=F(14), text_color=TENUE).grid(row=0, column=1, sticky="w")
        self.lbl_estado = ctk.CTkLabel(cab, text="● Buscando Albion…", font=F(12), text_color=NARANJA)
        self.lbl_estado.grid(row=0, column=2, padx=12)
        self.lbl_silver = ctk.CTkLabel(cab, text="💰  —", font=F(14, True), text_color=ORO,
                                       fg_color=CARD, corner_radius=10, padx=14, pady=6)
        self.lbl_silver.grid(row=0, column=3, padx=6)
        boton(cab, "⚙  Ajustes", self._ajustes, width=110).grid(row=0, column=4, padx=(6, 0))

        # --- panel izquierdo (etapas) ---
        self.panel = Tarjeta(self, width=410)
        self.panel.grid(row=1, column=0, sticky="nsew", padx=(20, 10), pady=(4, 20))
        self.panel.grid_propagate(False)
        self.panel.grid_columnconfigure(0, weight=1)
        self.panel.grid_rowconfigure(0, weight=1)
        self.etapas = {"mn": self._etapa_mn(), "bloques": self._etapa_bloques(), "ciudad": self._etapa_ciudad()}

        # --- panel derecho (oportunidades + registro) ---
        der = ctk.CTkFrame(self, fg_color="transparent")
        der.grid(row=1, column=1, sticky="nsew", padx=(10, 20), pady=(4, 20))
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(0, weight=1)
        self._panel_oportunidades(der)
        self.logs = self._panel_texto(der, 1, "Logs", "cada escaneo, como en la consola")
        self.registro = self._panel_texto(der, 2, "Registro", "lo importante: oportunidades, errores, ajustes")

    def _titulo(self, master, numero, texto, sub):
        """Título de la etapa. Devuelve el primer widget, para empaquetar los botones de abajo
        antes que el resto (así nunca quedan tapados si falta altura)."""
        titulo = ctk.CTkLabel(master, text=f"{numero}  ·  {texto}", font=F(18, True), text_color=TEXTO,
                              anchor="w")
        titulo.pack(fill="x", padx=22, pady=(20, 2))
        ctk.CTkLabel(master, text=sub, font=F(12), text_color=TENUE, anchor="w", justify="left",
                     wraplength=360).pack(fill="x", padx=22, pady=(0, 14))
        return titulo

    # --- etapa 1: Mercado Negro ---
    def _etapa_mn(self):
        f = ctk.CTkFrame(self.panel, fg_color="transparent")
        arriba = self._titulo(f, "1", "Mercado Negro",
                     "En Caerleon abrí el Mercado Negro (pestaña Vender) y pasá las páginas que quieras. "
                     "Cada orden queda guardada.")
        caja = ctk.CTkFrame(f, fg_color=CARD2, corner_radius=12)
        caja.pack(fill="x", padx=22)
        self.lbl_mn_total = ctk.CTkLabel(caja, text="0", font=F(46, True), text_color=ORO)
        self.lbl_mn_total.pack(pady=(16, 0))
        ctk.CTkLabel(caja, text="órdenes capturadas", font=F(12), text_color=TENUE).pack()
        self.lbl_mn_pagina = ctk.CTkLabel(caja, text="Esperando la primera página…", font=F(12), text_color=TENUE)
        self.lbl_mn_pagina.pack(pady=(8, 16))

        self.caja_ultimo = ctk.CTkFrame(f, fg_color=CARD2, corner_radius=12)
        self.caja_ultimo.pack(fill="x", padx=22, pady=14)
        self.lbl_ultimo = ctk.CTkLabel(self.caja_ultimo, text="", font=F(12), text_color=TEXTO,
                                       justify="left", anchor="w", wraplength=330)
        self.lbl_ultimo.pack(fill="x", padx=14, pady=(12, 6))
        self.btn_ultimo = boton(self.caja_ultimo, "↺  Usar último escaneo", self._usar_ultimo)
        self.btn_ultimo.pack(fill="x", padx=14, pady=(0, 12))

        self.btn_terminar_mn = boton(f, "Terminar escaneo  →", self._terminar_mn, primario=True, height=46)
        self.btn_terminar_mn.pack(fill="x", side="bottom", padx=22, pady=22, before=arriba)
        return f

    # --- etapa 2: elegir bloques ---
    def _etapa_bloques(self):
        f = ctk.CTkFrame(self.panel, fg_color="transparent")
        arriba = self._titulo(f, "2", "Elegí los bloques",
                     "Tier.encantamiento a barrer. Cada bloque = poner los filtros una sola vez.")
        fila = ctk.CTkFrame(f, fg_color="transparent")
        fila.pack(fill="x", padx=22)
        boton(fila, "Todos", lambda: self._marcar_bloques(True), width=90, height=30).pack(side="left")
        boton(fila, "Ninguno", lambda: self._marcar_bloques(False), width=90, height=30).pack(side="left", padx=8)
        self.lista_bloques = ctk.CTkScrollableFrame(f, fg_color=CARD2, corner_radius=12)
        self.lista_bloques.pack(fill="both", expand=True, padx=22, pady=12)
        abajo = ctk.CTkFrame(f, fg_color="transparent")
        abajo.pack(fill="x", side="bottom", padx=22, pady=(0, 22), before=arriba)
        boton(abajo, "←", lambda: self._mostrar("mn"), width=50, height=46).pack(side="left")
        boton(abajo, "Empezar barrido  →", self._empezar_barrido, primario=True,
              height=46).pack(side="left", fill="x", expand=True, padx=(10, 0))
        return f

    # --- etapa 3: barrido en la ciudad ---
    def _etapa_ciudad(self):
        f = ctk.CTkFrame(self.panel, fg_color="transparent")
        arriba = self._titulo(f, "3", "Barrido en la ciudad",
                     f"En el buscador del mercado:  Ctrl+V  ·  Enter.  El siguiente nombre se copia solo. "
                     f"{self.cfg.tecla_saltar_bloque} salta el bloque sin salir del juego.")

        self.banner = ctk.CTkFrame(f, fg_color="#2b2414", corner_radius=12, border_width=2, border_color=ORO)
        self.banner.pack(fill="x", padx=22)
        ctk.CTkLabel(self.banner, text="FILTROS DEL MERCADO", font=F(11, True), text_color=ORO_OSC).pack(pady=(10, 0))
        self.lbl_filtros = ctk.CTkLabel(self.banner, text="—", font=F(21, True), text_color=ORO)
        self.lbl_filtros.pack(pady=(0, 10))

        tarjeta = ctk.CTkFrame(f, fg_color=CARD2, corner_radius=12)
        tarjeta.pack(fill="x", padx=22, pady=14)
        ctk.CTkLabel(tarjeta, text="📋  EN EL PORTAPAPELES", font=F(11, True), text_color=TENUE,
                     anchor="w").pack(fill="x", padx=16, pady=(12, 0))
        self.lbl_nombre = ctk.CTkLabel(tarjeta, text="—", font=F(17, True), text_color=TEXTO, anchor="w",
                                       justify="left", wraplength=300)
        self.lbl_nombre.pack(fill="x", padx=16, pady=(2, 0))
        self.lbl_nombre_info = ctk.CTkLabel(tarjeta, text="", font=F(12), text_color=TENUE, anchor="w")
        self.lbl_nombre_info.pack(fill="x", padx=16, pady=(0, 12))

        self.lbl_prog_bloque = ctk.CTkLabel(f, text="", font=F(12), text_color=TENUE, anchor="w")
        self.lbl_prog_bloque.pack(fill="x", padx=22)
        self.bar_bloque = ctk.CTkProgressBar(f, progress_color=ORO, fg_color=CARD2, height=10)
        self.bar_bloque.pack(fill="x", padx=22, pady=(2, 10))
        self.lbl_prog_total = ctk.CTkLabel(f, text="", font=F(12), text_color=TENUE, anchor="w")
        self.lbl_prog_total.pack(fill="x", padx=22)
        self.bar_total = ctk.CTkProgressBar(f, progress_color=VERDE, fg_color=CARD2, height=10)
        self.bar_total.pack(fill="x", padx=22, pady=(2, 8))

        self.lbl_aviso = ctk.CTkLabel(f, text="", font=F(13, True), text_color=ROJO, wraplength=360)
        self.lbl_aviso.pack(fill="x", padx=22, pady=4)

        abajo = ctk.CTkFrame(f, fg_color="transparent")
        abajo.pack(fill="x", side="bottom", padx=22, pady=(0, 22), before=arriba)
        abajo.grid_columnconfigure((0, 1), weight=1)
        boton(abajo, f"⏭  Saltar bloque   ({self.cfg.tecla_saltar_bloque} desde el juego)",
              self._accion(lambda s: s.saltar_bloque())).grid(row=0, column=0, columnspan=2, sticky="ew")
        boton(abajo, "Saltar nombre", self._accion(lambda s: s.saltar_nombre())).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        boton(abajo, "Recopiar", self._accion(lambda s: s.recopiar())).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=(8, 0))
        boton(abajo, "⟳  Nuevo escaneo del Mercado Negro", self._reiniciar).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        return f

    def _crear_tabla(self, master, columnas):
        """Treeview oscuro con scroll. columnas = [(clave, título, ancho, ancla), ...]"""
        marco = ctk.CTkFrame(master, fg_color=CARD2, corner_radius=10)
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(0, weight=1)
        tabla = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings", style="Op.Treeview")
        for col, txt, ancho, ancla in columnas:
            tabla.heading(col, text=txt, anchor=ancla)
            tabla.column(col, width=ancho, anchor=ancla, stretch=(col == "item"))
        tabla.tag_configure("alta", foreground=VERDE)
        tabla.tag_configure("media", foreground=ORO)
        tabla.tag_configure("perdida", foreground=ROJO)
        tabla.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(marco, orient="vertical", command=tabla.yview, style="Op.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        tabla.configure(yscrollcommand=sb.set)
        return marco, tabla

    def _menu(self, opciones):
        menu = tk.Menu(self, tearoff=0, bg=CARD2, fg=TEXTO, activebackground="#3a3220",
                       activeforeground=ORO, bd=0, font=(FUENTE, 10))
        for texto, accion in opciones:
            if texto is None:
                menu.add_separator()
            else:
                menu.add_command(label=texto, command=accion)
        return menu

    def _fila_clic_derecho(self, tabla, evento):
        fila = tabla.identify_row(evento.y)
        if fila:
            tabla.selection_set(fila)
        return fila

    def _panel_oportunidades(self, master):
        t = Tarjeta(master)
        t.grid(row=0, column=0, sticky="nsew")
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(1, weight=1)
        cab = ctk.CTkFrame(t, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 8))
        self.selector = ctk.CTkSegmentedButton(
            cab, values=["Oportunidades", "Para vender", "Historial"], command=self._ver_pestana,
            font=F(13, True), selected_color=ORO, selected_hover_color=ORO_OSC, unselected_color=CARD2,
            unselected_hover_color=BORDE, fg_color=CARD2, text_color=TEXTO, height=34)
        self.selector.pack(side="left")
        self.selector.set("Oportunidades")
        self.lbl_cant_ops = ctk.CTkLabel(cab, text="0", font=F(12, True), text_color="#16130b",
                                         fg_color=ORO, corner_radius=8, width=34)
        self.lbl_cant_ops.pack(side="left", padx=10)
        ctk.CTkLabel(cab, text="clic derecho = opciones  ·  doble clic = copiar nombre", font=F(11),
                     text_color=TENUE).pack(side="right")

        # Oportunidades
        self.marco_ops, self.tabla = self._crear_tabla(t, [
            ("pct", "%", 64, "e"), ("gan", "Ganancia", 100, "e"), ("item", "Ítem", 260, "w"),
            ("calidad", "Calidad", 110, "w"), ("comprar", "Comprar a", 110, "e"),
            ("mn", "MN paga", 150, "e"), ("uds", "Uds.", 46, "center"), ("visto", "Visto", 80, "e")])
        self.tabla.bind("<Double-1>", lambda _e: self._copiar_op())
        self.tabla.bind("<Button-3>", self._menu_op)
        self.filas = {}

        # Para vender
        self.marco_venta, self.tabla_venta = self._crear_tabla(t, [
            ("item", "Ítem", 260, "w"), ("calidad", "Calidad", 110, "w"), ("uds", "Uds.", 46, "center"),
            ("pagaste", "Pagaste", 110, "e"), ("mn", "MN paga", 150, "e"),
            ("esperada", "Ganancia esperada", 130, "e"), ("cuando", "Comprado", 90, "e")])
        self.tabla_venta.bind("<Double-1>", lambda _e: self._copiar_compra(self.tabla_venta))
        self.tabla_venta.bind("<Button-3>", self._menu_venta)

        # Historial
        self.marco_hist, self.tabla_hist = self._crear_tabla(t, [
            ("fecha", "Vendido", 120, "w"), ("item", "Ítem", 260, "w"), ("uds", "Uds.", 46, "center"),
            ("pagaste", "Pagaste", 110, "e"), ("vendiste", "Vendiste a", 110, "e"),
            ("ganancia", "Ganancia real", 120, "e")])
        self.tabla_hist.bind("<Button-3>", self._menu_hist)

        self.lbl_total = ctk.CTkLabel(t, text="Todavía no hay oportunidades.", font=F(13, True),
                                      text_color=TENUE, anchor="w")
        self.lbl_total.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 14))
        self.pestana = "Oportunidades"
        self._ver_pestana("Oportunidades")

    def _ver_pestana(self, nombre):
        self.pestana = nombre
        marcos = {"Oportunidades": self.marco_ops, "Para vender": self.marco_venta, "Historial": self.marco_hist}
        for n, marco in marcos.items():
            if n == nombre:
                marco.grid(row=1, column=0, sticky="nsew", padx=16)
            else:
                marco.grid_remove()
        self._actualizar_pie()

    def _panel_texto(self, master, fila, titulo, sub):
        """Panel de texto de solo lectura (Logs / Registro), todos de la misma altura."""
        t = Tarjeta(master, height=150)
        t.grid(row=fila, column=0, sticky="ew", pady=(12, 0))
        t.grid_propagate(False)
        t.grid_columnconfigure(1, weight=1)
        t.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(t, text=titulo, font=F(13, True), text_color=TEXTO, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(18, 8), pady=(8, 0))
        ctk.CTkLabel(t, text=sub, font=F(11), text_color=TENUE, anchor="w").grid(
            row=0, column=1, sticky="w", pady=(8, 0))
        caja = ctk.CTkTextbox(t, fg_color=CARD2, text_color=TEXTO, font=ctk.CTkFont(family="Consolas", size=11),
                              corner_radius=10, wrap="none")
        caja.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=14, pady=(4, 12))
        caja.configure(state="disabled")
        return caja

    # =====================================================================
    # Navegación
    # =====================================================================
    def _mostrar(self, etapa):
        for nombre, frame in self.etapas.items():
            if nombre == etapa:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_remove()
        self.etapa_visible = etapa
        if etapa == "mn":
            self._refrescar_ultimo()

    def _refrescar_ultimo(self):
        ruta, datos = self.sesion.ultimo_escaneo_previo()
        if ruta:
            self.lbl_ultimo.configure(text=f"Último escaneo guardado\n{len(datos['ordenes'])} órdenes · "
                                           f"{hace(time.time() - datos['fecha'])}\n{os.path.basename(ruta)}")
            self.btn_ultimo.configure(state="normal")
        else:
            self.lbl_ultimo.configure(text="Todavía no hay escaneos guardados.")
            self.btn_ultimo.configure(state="disabled")

    def _usar_ultimo(self):
        usado = self.sesion.reutilizar_escaneo()
        if usado:
            ruta, datos = usado
            self.log(f"Usando {os.path.basename(ruta)} ({len(datos['ordenes'])} órdenes, "
                     f"{hace(time.time() - datos['fecha'])})")
            self._terminar_mn()

    def _terminar_mn(self):
        bloques = self.sesion.bloques()
        if not bloques:
            messagebox.showinfo("Albion Market", "Todavía no hay órdenes del Mercado Negro.\n\n"
                                "Pasá algunas páginas en el Mercado Negro o usá el último escaneo.")
            return
        for w in self.lista_bloques.winfo_children():
            w.destroy()
        self.vars_bloques = {}
        for bloque, nombres, mejor in bloques:
            var = tk.BooleanVar(value=True)
            self.vars_bloques[bloque] = var
            fila = ctk.CTkFrame(self.lista_bloques, fg_color="transparent")
            fila.pack(fill="x", pady=3, padx=4)
            ctk.CTkCheckBox(fila, text=f"  {bloque}", variable=var, font=F(15, True), text_color=TEXTO,
                            fg_color=ORO, hover_color=ORO_OSC, checkmark_color="#16130b",
                            border_color=TENUE, width=90).pack(side="left")
            ctk.CTkLabel(fila, text=f"{nombres} nombres", font=F(12), text_color=TEXTO).pack(side="left", padx=6)
            ctk.CTkLabel(fila, text=f"hasta {m(mejor)}", font=F(12), text_color=TENUE).pack(side="right", padx=6)
        self._mostrar("bloques")

    def _marcar_bloques(self, valor):
        for var in self.vars_bloques.values():
            var.set(valor)

    def _empezar_barrido(self):
        elegidos = {b for b, v in self.vars_bloques.items() if v.get()}
        if not elegidos:
            messagebox.showinfo("Albion Market", "Elegí al menos un bloque.")
            return
        self._mostrar("ciudad")
        self.lbl_aviso.configure(text="")
        self.sesion.iniciar_barrido(elegidos)
        self.log(f"Barrido iniciado: {', '.join(sorted(elegidos, reverse=True))}")

    def _reiniciar(self):
        if not messagebox.askyesno("Albion Market", "¿Empezar un escaneo nuevo del Mercado Negro?\n\n"
                                   "La lista de oportunidades actual se limpia."):
            return
        self.sesion = self._nueva_sesion()
        self.lbl_mn_total.configure(text="0")
        self.lbl_mn_pagina.configure(text="Esperando la primera página…")
        self.tabla_sucia = True
        self._mostrar("mn")
        self.log("Nueva sesión: escaneá el Mercado Negro.")

    def _accion(self, fn):
        return lambda: fn(self.sesion)

    def _enter(self):
        if self.etapa_visible == "ciudad":
            self.sesion.saltar_bloque()

    # =====================================================================
    # Eventos de la sesión (siempre en el hilo de la interfaz)
    # =====================================================================
    def _evento(self, tipo, **d):
        if tipo == "silver":
            self.silver_conocido, self.silver_fecha = d["cantidad"], time.time()
            guardar_estado(silver=self.silver_conocido, fecha=self.silver_fecha)
            self._mostrar_silver(en_vivo=True)
            self.consola(f"💰 Silver: {m(d['cantidad'])}")
            self.tabla_sucia = True
        elif tipo == "mn":
            self.lbl_mn_total.configure(text=m(d["total"]))
            self.lbl_mn_pagina.configure(text=f"Última página: +{d['nuevas']} órdenes  ·  "
                                              f"{m(d['minimo'])} – {m(d['maximo'])}")
            self.consola(f"[MN] +{d['nuevas']} órdenes ({m(d['minimo'])} – {m(d['maximo'])}) → "
                         f"{d['total']} guardadas")
        elif tipo == "nombre":
            g = d["grupo"]
            if d["cambio_bloque"]:
                sonido.cambio_bloque()
                self.lbl_filtros.configure(text=f"TIER {g.tier}   ·   ENCANTAMIENTO {g.encantamiento}")
                self._destello()
                self.consola("=" * 56)
                self.consola(f"🔧 PONÉ LOS FILTROS →  TIER: {g.tier}   ENCANTAMIENTO: {g.encantamiento}")
                self.consola("=" * 56)
            self.lbl_aviso.configure(text="")
            self.consola(f"📋 ({d['indice'] + 1}/{d['total']}) {g.nombre} {g.bloque}  [{len(g.objetivos)} órdenes, "
                         f"hasta {m(g.mejor_precio)}]  · quedan {d['faltan_bloque']} en {g.bloque}")
            self.lbl_nombre.configure(text=f"{g.nombre}  {g.bloque}")
            self.lbl_nombre_info.configure(text=f"{len(g.objetivos)} órdenes del MN  ·  hasta {m(g.mejor_precio)}")
            self.lbl_prog_bloque.configure(text=f"Bloque {g.bloque}:  {d['hechos_bloque']} / {d['total_bloque']}"
                                                f"   (quedan {d['faltan_bloque']})")
            self.bar_bloque.set(d["hechos_bloque"] / max(1, d["total_bloque"]))
            self.lbl_prog_total.configure(text=f"Total:  {d['indice']} / {d['total']}")
            self.bar_total.set(d["indice"] / max(1, d["total"]))
            if not d.get("copiado", True):
                self.lbl_aviso.configure(text="⚠  No se pudo copiar al portapapeles: tocá «Recopiar»")
        elif tipo == "recopiado":
            g = d["grupo"]
            if d["ok"]:
                self.consola(f"↺ Esa búsqueda no era la de la lista: volví a copiar «{g.nombre}» ({g.bloque})")
            else:
                self.lbl_aviso.configure(text="⚠  No se pudo copiar al portapapeles: tocá «Recopiar»")
        elif tipo == "filtro_mal":
            sonido.error()
            self.lbl_aviso.configure(text=f"⚠  El filtro de {d['campo']} está en {d['puesto']}: "
                                          f"ponelo en {d['esperado']} y repetí Ctrl+V · Enter")
            self.consola(f"⚠️  El filtro de {d['campo']} está en {d['puesto']}: ponelo en {d['esperado']}")
        elif tipo == "oportunidad":
            sonido.oportunidad()
            op = d["op"]
            texto = (f"🔔 {self.cat.etiqueta(op.item_id)} | comprá {CALIDADES[op.calidad]} a {m(op.precio_compra)}"
                     f" → MN paga {m(op.objetivo.precio)} | +{m(op.ganancia)} (+{op.porcentaje:.1f}%)")
            self.consola(texto)
            self.log(texto)
            self.tabla_sucia = True
        elif tipo == "ciudad":
            self.tabla_sucia = True
        elif tipo == "salto":
            self.consola(f"⏭️  Bloque {d['bloque']} saltado ({d['saltados']} nombres sin buscar)")
        elif tipo == "fin":
            self.lbl_nombre.configure(text="✅  Terminaste la lista")
            self.lbl_nombre_info.configure(text="Revisá las oportunidades de la derecha.")
            self.bar_bloque.set(1)
            self.bar_total.set(1)
            self.lbl_prog_total.configure(text="Total: completo")
            self.consola("✅ Terminaste la lista.")
            if self.sesion.revisar_luego:
                self.log(f"Podrían tener más en la página 2: {', '.join(self.sesion.revisar_luego)}")

    def _mostrar_silver(self, en_vivo=False):
        if self.silver_conocido is None:
            self.lbl_silver.configure(text="💰  —", text_color=TENUE)
        elif en_vivo:
            self.lbl_silver.configure(text=f"💰  {m(self.silver_conocido)}", text_color=ORO)
        else:  # último valor guardado: se actualiza cuando compres o vendas algo
            self.lbl_silver.configure(text=f"💰  {m(self.silver_conocido)}  ·  {hace(time.time() - self.silver_fecha)}",
                                      text_color=TENUE)

    def _destello(self, n=6):
        if n <= 0:
            self.banner.configure(border_color=ORO)
            return
        self.banner.configure(border_color=TEXTO if n % 2 else ORO)
        self.after(140, lambda: self._destello(n - 1))

    def _refrescar_tabla(self):
        ops = self.sesion.oportunidades()
        self.tabla.delete(*self.tabla.get_children())
        self.filas = {}
        for op in ops:
            o = op.objetivo
            tag = "alta" if op.porcentaje >= 20 else "media" if op.porcentaje >= 10 else ""
            iid = self.tabla.insert("", "end", tags=(tag,), values=(
                f"{op.porcentaje:.1f}%", f"+{m(op.ganancia)}", self.cat.etiqueta(op.item_id),
                CALIDADES[op.calidad], m(op.precio_compra), f"{m(o.precio)}  ({CALIDADES[o.calidad]}+)",
                op.unidades, hace(time.time() - op.visto) if op.visto else ""))
            self.filas[iid] = op
        self.ops_actuales = ops
        self._actualizar_pie()

    def _actualizar_pie(self):
        if self.pestana == "Oportunidades":
            ops = getattr(self, "ops_actuales", [])
            self.lbl_cant_ops.configure(text=str(len(ops)))
            if ops:
                r = self.sesion.resumen(ops)
                texto = (f"Total:  invertís {m(r['inversion'])}  →  ganás {m(r['ganancia'])}  "
                         f"(+{r['porcentaje']:.1f}%)  en {r['items']} ítems")
                color = VERDE
                silver = self.sesion.motor.silver
                if silver is not None and r["inversion"] > silver:
                    texto += "   ·   tu silver no alcanza para todo: empezá por arriba"
                    color = NARANJA
                self.lbl_total.configure(text=texto, text_color=color)
            else:
                self.lbl_total.configure(text="Todavía no hay oportunidades.", text_color=TENUE)
            return
        r = self.compras.resumen()
        if self.pestana == "Para vender":
            pend = self.compras.pendientes()
            self.lbl_cant_ops.configure(text=str(len(pend)))
            if pend:
                self.lbl_total.configure(text=f"Para llevar al Mercado Negro:  invertido {m(r['invertido'])}  →  "
                                              f"ganancia esperada +{m(r['esperado'])}", text_color=ORO)
            else:
                self.lbl_total.configure(text="Nada pendiente. Marcá oportunidades como «Comprado» con clic derecho.",
                                         text_color=TENUE)
        else:
            self.lbl_cant_ops.configure(text=str(r["ventas"]))
            color = VERDE if r["total"] >= 0 else ROJO
            self.lbl_total.configure(text=f"Hoy:  {'+' if r['hoy'] >= 0 else ''}{m(r['hoy'])}     ·     "
                                          f"Total:  {'+' if r['total'] >= 0 else ''}{m(r['total'])}  "
                                          f"en {r['ventas']} ventas", text_color=color)

    def _op_seleccionada(self):
        sel = self.tabla.selection()
        return self.filas.get(sel[0]) if sel else None

    def _copiar_op(self):
        op = self._op_seleccionada()
        if op:
            nombre = self.cat.nombre(op.item_id)
            clipboard.copiar(nombre)
            self.log(f"📋 Copiado para comprar: {nombre}")

    def _menu_op(self, evento):
        if not self._fila_clic_derecho(self.tabla, evento):
            return
        self._menu([("✔  Comprado", self._marcar_comprado), ("📋  Copiar nombre", self._copiar_op), (None, None),
                    ("✖  Descartar", self._descartar_op)]).tk_popup(evento.x_root, evento.y_root)

    def _marcar_comprado(self):
        op = self._op_seleccionada()
        if not op:
            return
        rec = self.compras.agregar(op, self.cat.etiqueta(op.item_id), self.cfg.impuesto_venta)
        self.sesion.motor.reservados.add(op.objetivo.id)
        self.sesion.motor.excluir_ofertas.add(op.id_oferta)
        self.log(f"✔ Comprado: {rec['nombre']} ({CALIDADES[op.calidad]}) a {m(op.precio_compra)} "
                 f"→ ganancia esperada +{m(rec['ganancia_esperada'])}")
        self._refrescar_compras()
        self.tabla_sucia = True

    def _descartar_op(self):
        op = self._op_seleccionada()
        if op:
            self.sesion.motor.excluir_ofertas.add(op.id_oferta)
            self.log(f"✖ Descartada: {self.cat.etiqueta(op.item_id)} a {m(op.precio_compra)}")
            self.tabla_sucia = True

    def _compra_seleccionada(self, tabla):
        sel = tabla.selection()
        return next((r for r in self.compras.items if r["id"] == sel[0]), None) if sel else None

    def _copiar_compra(self, tabla):
        r = self._compra_seleccionada(tabla)
        if r:
            clipboard.copiar(self.cat.nombre(r["item_id"]))
            self.log(f"📋 Copiado: {self.cat.nombre(r['item_id'])}")

    def _menu_venta(self, evento):
        if not self._fila_clic_derecho(self.tabla_venta, evento):
            return
        self._menu([("💰  Vendido al precio esperado", lambda: self._vender(None)),
                    ("💰  Vendido a otro precio…", lambda: self._vender("pedir")),
                    ("📋  Copiar nombre", lambda: self._copiar_compra(self.tabla_venta)), (None, None),
                    ("↩  Deshacer compra", self._deshacer_compra)]).tk_popup(evento.x_root, evento.y_root)

    def _vender(self, precio):
        r = self._compra_seleccionada(self.tabla_venta)
        if not r:
            return
        if precio == "pedir":
            texto = ctk.CTkInputDialog(title="Vendido a otro precio",
                                       text=f"{r['nombre']}\n¿A cuánto lo vendiste? (por unidad, antes del impuesto)"
                                       ).get_input()
            try:
                precio = int((texto or "").replace(".", "").replace(",", "").strip())
            except ValueError:
                return
        r = self.compras.vender(r["id"], precio if precio else r["mn_precio"])
        self.log(f"💰 Vendido: {r['nombre']} a {m(r['precio_venta'])} → ganancia real "
                 f"{'+' if r['ganancia_real'] >= 0 else ''}{m(r['ganancia_real'])}")
        self._refrescar_compras()

    def _deshacer_compra(self):
        r = self._compra_seleccionada(self.tabla_venta)
        if r and messagebox.askyesno("Albion Market", f"¿Deshacer la compra de {r['nombre']}?"):
            self.compras.deshacer(r["id"])
            self.sesion.motor.reservados.discard(r["orden_mn"])
            self.sesion.motor.excluir_ofertas.discard(r.get("id_oferta"))
            self.log(f"↩ Compra deshecha: {r['nombre']}")
            self._refrescar_compras()
            self.tabla_sucia = True

    def _menu_hist(self, evento):
        if not self._fila_clic_derecho(self.tabla_hist, evento):
            return
        self._menu([("✖  Borrar del historial", self._borrar_hist)]).tk_popup(evento.x_root, evento.y_root)

    def _borrar_hist(self):
        r = self._compra_seleccionada(self.tabla_hist)
        if r and messagebox.askyesno("Albion Market", f"¿Borrar la venta de {r['nombre']} del historial?"):
            self.compras.deshacer(r["id"])
            self._refrescar_compras()

    def _refrescar_compras(self):
        self.tabla_venta.delete(*self.tabla_venta.get_children())
        for r in self.compras.pendientes():
            self.tabla_venta.insert("", "end", iid=r["id"], tags=("media",), values=(
                r["nombre"], CALIDADES[r["calidad"]], r["unidades"], m(r["precio_compra"]),
                f"{m(r['mn_precio'])}  ({CALIDADES[r['mn_calidad']]}+)", f"+{m(r['ganancia_esperada'])}",
                hace(time.time() - r["fecha_compra"])))
        self.tabla_hist.delete(*self.tabla_hist.get_children())
        for r in self.compras.vendidos():
            g = r["ganancia_real"]
            self.tabla_hist.insert("", "end", iid=r["id"], tags=("alta" if g >= 0 else "perdida",), values=(
                datetime.fromtimestamp(r["fecha_venta"]).strftime("%d/%m %H:%M"), r["nombre"], r["unidades"],
                m(r["precio_compra"]), m(r["precio_venta"]), f"{'+' if g >= 0 else ''}{m(g)}"))
        self._actualizar_pie()

    @staticmethod
    def _escribir(caja, texto, maximo=1500):
        caja.configure(state="normal")
        caja.insert("end", f"{datetime.now():%H:%M:%S}  {texto}\n")
        lineas = int(caja.index("end-1c").split(".")[0])
        if lineas > maximo:
            caja.delete("1.0", f"{lineas - maximo}.0")
        caja.see("end")
        caja.configure(state="disabled")

    def log(self, texto):
        """Registro: solo lo importante."""
        self._escribir(self.registro, texto, 400)

    def consola(self, texto):
        """Logs: todo lo que se escanea, como en la consola."""
        self._escribir(self.logs, texto)

    # =====================================================================
    # Captura de red
    # =====================================================================
    def _iniciar_sniffer(self):
        self.sniffer = Sniffer(lambda pid, dato: self.cola.put(("dato", pid, dato)))

        def correr():
            try:
                self.sniffer.correr()
            except Exception as e:  # se muestra en la interfaz
                self.cola.put(("error", str(e)))

        threading.Thread(target=correr, daemon=True).start()
        self.log("Escuchando el tráfico del juego (solo lectura).")

    def _iniciar_tecla(self):
        tecla = self.cfg.tecla_saltar_bloque
        try:
            ok = hotkey.escuchar(tecla, lambda: self.cola.put(("tecla",)))
        except ValueError as e:
            self.log(f"❌ {e}")
            return
        if ok:
            self.log(f"⌨ {tecla} = saltar bloque (funciona desde el juego).")
        else:
            self.log(f"❌ No se pudo usar {tecla}: otra app la está usando. Cambiala en Ajustes.")

    def _drenar(self):
        """Procesa lo que llegó de la red. Un error en un dato no frena la app: se anota y sigue."""
        try:
            for _ in range(500):
                try:
                    item = self.cola.get_nowait()
                except queue.Empty:
                    break
                try:
                    if item[0] == "dato":
                        self.sesion.procesar(item[1], item[2])
                    elif item[0] == "tecla":
                        self._enter()
                    else:
                        self.log(f"❌ Error de captura: {item[1]}")
                except Exception as e:
                    self._error_interno(e)
            ahora = time.time()
            if self.tabla_sucia and ahora - self.ultimo_refresco > 0.4:
                self.tabla_sucia = False
                self.ultimo_refresco = ahora
                self._refrescar_tabla()
        except Exception as e:
            self._error_interno(e)
        finally:
            self.after(40, self._drenar)

    def _error_interno(self, e):
        import traceback
        os.makedirs(rutas.LOGS, exist_ok=True)
        with open(os.path.join(rutas.LOGS, "errores.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{traceback.format_exc()}\n")
        self.log(f"❌ Error interno (guardado en logs/errores.log): {e}")

    def _chequear_albion(self):
        if procmap.albion_processes():
            self.lbl_estado.configure(text="● Albion detectado", text_color=VERDE)
        else:
            self.lbl_estado.configure(text="● Esperando Albion…", text_color=NARANJA)
        self.after(3000, self._chequear_albion)

    # =====================================================================
    # Ajustes
    # =====================================================================
    def _ajustes(self):
        v = ctk.CTkToplevel(self)
        v.title("Ajustes")
        v.geometry("440x470")
        v.configure(fg_color=BG)
        v.transient(self)
        v.grab_set()
        campos = (("impuesto_venta", "Impuesto de venta (0.08 = 8%, sin premium)", float),
                  ("ganancia_min", "Ganancia mínima por ítem (silver)", int),
                  ("porcentaje_min", "Porcentaje mínimo de ganancia (%)", float),
                  ("precio_mn_min", "Ignorar órdenes del MN que pagan menos de", int),
                  ("tecla_saltar_bloque", "Tecla para saltar bloque desde el juego (F1–F24, al reiniciar)", str))
        entradas = {}
        for clave, texto, _tipo in campos:
            ctk.CTkLabel(v, text=texto, font=F(12), text_color=TENUE, anchor="w").pack(fill="x", padx=24, pady=(14, 2))
            e = ctk.CTkEntry(v, font=F(14), fg_color=CARD2, border_color=BORDE, text_color=TEXTO)
            e.insert(0, str(getattr(self.cfg, clave)))
            e.pack(fill="x", padx=24)
            entradas[clave] = e

        def guardar():
            try:
                for clave, _texto, tipo in campos:
                    valor = entradas[clave].get().strip()
                    if tipo is str:
                        hotkey.codigo_tecla(valor)  # valida
                        setattr(self.cfg, clave, valor.upper())
                    else:
                        setattr(self.cfg, clave, tipo(valor.replace(",", ".")))
            except ValueError:
                messagebox.showerror("Ajustes", "Revisá los valores: números, y la tecla entre F1 y F24.", parent=v)
                return
            guardar_config(self.cfg)
            self.tabla_sucia = True
            self.log(f"Ajustes guardados: impuesto {self.cfg.impuesto_venta:.0%} · mín {m(self.cfg.ganancia_min)} "
                     f"· {self.cfg.porcentaje_min}%")
            v.destroy()

        boton(v, "Guardar", guardar, primario=True, height=42).pack(fill="x", padx=24, pady=22)


def main():
    if not es_admin():
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Albion Market", "Abrí Albion Market como administrador\n"
                             "(clic derecho → Ejecutar como administrador).\n\n"
                             "Windows lo exige para poder leer el tráfico del juego.")
        return
    App().mainloop()


if __name__ == "__main__":
    main()
