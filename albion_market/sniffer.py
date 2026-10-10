"""Une captura + decodificador + intérprete, separando el tráfico por cliente (PID)."""
import threading
import time

from . import capture, procmap
from .market import Interprete
from .photon import PhotonDecoder


class Sniffer:
    """Llama on_dato(pid, dato) por cada Pagina/Silver interpretado.

    Solo escucha: no envía nada al juego.
    """

    def __init__(self, on_dato, backend="raw", ip=None):
        self.on_dato = on_dato
        self.backend = backend
        self.ip = ip
        self.pids = [pid for pid, _ in procmap.albion_processes()]
        self._puerto_pid = {}
        self._decoders = {}      # (pid, entrante) -> PhotonDecoder
        self._interpretes = {}   # pid -> Interprete (une solicitudes salientes con respuestas entrantes)
        self._stop = threading.Event()

    def _refrescar_puertos(self):
        self.pids = [pid for pid, _ in procmap.albion_processes()]
        self._puerto_pid.update(procmap.udp_port_to_pid(self.pids))

    def _on_packet(self, sport, dport, payload):
        entrante = sport in capture.ALBION_PORTS
        local = dport if entrante else sport
        pid = self._puerto_pid.get(local)
        if pid is None:
            return
        decoder = self._decoders.setdefault((pid, entrante), PhotonDecoder())
        interprete = self._interpretes.setdefault(pid, Interprete())
        for msg in decoder.feed(payload):
            dato = interprete.procesar(msg)
            if dato is not None:
                self.on_dato(pid, dato)

    def reproducir(self, ruta):
        """Re-procesa una captura cruda (logs/*.crudo.jsonl) sin el juego, para pruebas."""
        import json
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                d = json.loads(linea)
                pid, entrante = d["pid"], d["dir"] == "in"
                decoder = self._decoders.setdefault((pid, entrante), PhotonDecoder())
                interprete = self._interpretes.setdefault(pid, Interprete())
                for msg in decoder.feed(bytes.fromhex(d["hex"])):
                    dato = interprete.procesar(msg)
                    if dato is not None:
                        self.on_dato(pid, dato)

    def detener(self):
        self._stop.set()

    def correr(self):
        """Bloquea hasta detener() o Ctrl+C."""
        self._refrescar_puertos()

        def refresco():
            while not self._stop.is_set():
                self._refrescar_puertos()
                time.sleep(3)

        threading.Thread(target=refresco, daemon=True).start()
        if self.backend == "raw":
            capture.capture_raw(self._on_packet, ip=self.ip, stop=self._stop.is_set)
        else:
            capture.capture_npcap(self._on_packet, stop=self._stop.is_set)
