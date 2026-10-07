"""Comandos manuais para rele USB serial com protocolo LCUS-1."""

import argparse
import math
import time

import serial
from serial.tools import list_ports


def localizar_rele():
    portas = [p.device for p in list_ports.comports()
              if (p.vid, p.pid) == (0x1A86, 0x7523)]
    if not portas:
        raise RuntimeError("Relé USB CH340 não encontrado; verifique a conexão USB")
    if len(portas) != 1:
        raise RuntimeError("Mais de um CH340 encontrado; não foi possível identificar o relé")
    return portas[0]


def send(port, enabled):
    packet = bytes((0xA0, 1, int(enabled), 0xA1 + int(enabled)))
    if port.write(packet) != len(packet):
        raise IOError("Comando incompleto")
    port.flush()
    print(f"{port.port}: {'LIGAR' if enabled else 'DESLIGAR'} [{packet.hex(' ')}]", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("listar", "ligar", "desligar", "pulso", "teste"))
    parser.add_argument("--porta", help="porta manual; por padrão detecta o único CH340 conectado")
    parser.add_argument("--segundos", type=float, default=1.0)
    args = parser.parse_args()
    if args.action == "listar":
        for device in list_ports.comports():
            print(device.device, device.description, device.hwid)
        return
    if not math.isfinite(args.segundos) or not 0 < args.segundos <= 60:
        parser.error("--segundos deve estar entre 0 (exclusivo) e 60")
    if args.porta is None:
        try:
            args.porta = localizar_rele()
        except RuntimeError as erro:
            parser.error(str(erro))
    devices = [p for p in list_ports.comports() if p.device.upper() == args.porta.upper()]
    if len(devices) != 1 or (devices[0].vid, devices[0].pid) != (0x1A86, 0x7523):
        parser.error("A porta escolhida nao corresponde ao USB-SERIAL CH340 esperado (1A86:7523)")
    with serial.Serial(args.porta, 9600, bytesize=8, parity="N", stopbits=1,
                       timeout=0.5, write_timeout=2, xonxoff=False,
                       rtscts=False, dsrdtr=False) as port:
        if args.action in ("ligar", "desligar"):
            send(port, args.action == "ligar")
            return
        try:
            send(port, False)
            time.sleep(1)
            for _ in range(3 if args.action == "teste" else 1):
                send(port, True)
                time.sleep(args.segundos)
                send(port, False)
                time.sleep(1)
        finally:
            send(port, False)
    print("Sequencia concluida; comando final: DESLIGAR. Confirme os cliques no modulo.")


if __name__ == "__main__":
    main()
