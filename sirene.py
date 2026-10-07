"""Pulsos do relé em uma thread dedicada, sem bloquear a balança."""

import queue
import threading

import serial
from relay_usb import send, localizar_rele


class Sirene:
    def __init__(self, informar):
        self.informar = informar
        self.parar = threading.Event()
        self.fila = queue.Queue()
        self.worker = threading.Thread(target=self._executar, daemon=True)
        self.worker.start()

    def acionar(self):
        self.fila.put(5)

    def _executar(self):
        while not self.parar.is_set():
            try:
                segundos = self.fila.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.parar.is_set():
                break
            try:
                nome_porta = localizar_rele()
                with serial.Serial(nome_porta, 9600, timeout=0.5, write_timeout=2,
                                   xonxoff=False, rtscts=False, dsrdtr=False) as porta:
                    try:
                        send(porta, True)
                        self.informar(f"Sirene: acionada por 5 segundos ({nome_porta}).")
                        self.parar.wait(segundos)
                    finally:
                        send(porta, False)
                self.informar("Sirene: desligada.")
            except Exception as erro:
                self.informar(f"Sirene: falha no relé ({type(erro).__name__}): {erro}.")

    def close(self):
        self.parar.set()
        self.worker.join()
