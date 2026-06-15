"""Coletor avançado de diagnóstico da balança serial.

Execute este script nos dois computadores, de preferência com a balança ligada e
transmitindo, e envie os arquivos ``debug2_*.log`` gerados para comparação.

Exemplos:
    python debug2.py --port COM3 --duration 120
    python debug2.py --auto --duration 60
"""

import argparse
import csv
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError as exc:  # pragma: no cover - ajuda quando pyserial não existe
    print("ERRO: pyserial não está instalado. Rode: pip install pyserial")
    raise SystemExit(2) from exc

PADRAO_PESO = re.compile(r"(ST|US),GS,([+-]\d+)kg")
DEFAULT_BAUDRATE = 9600
DEFAULT_DURATION = 120
READ_POLL_SECONDS = 0.01
COMMAND_TIMEOUT_SECONDS = 8


class Logger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def write(self, message=""):
        line = f"[{timestamp()}] {message}" if message else ""
        print(line)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def section(self, title):
        self.write()
        self.write("=" * 80)
        self.write(title)
        self.write("=" * 80)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def safe_run(command):
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            errors="replace",
            shell=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return completed.returncode, output.strip()
    except Exception as exc:  # noqa: BLE001 - diagnóstico deve capturar tudo
        return None, f"{type(exc).__name__}: {exc!r}"


def log_command(logger, command):
    logger.write(f"$ {' '.join(command)}")
    code, output = safe_run(command)
    logger.write(f"exit_code={code}")
    if output:
        for line in output.splitlines():
            logger.write(f"  {line}")
    else:
        logger.write("  <sem saída>")


def collect_system_info(logger):
    logger.section("INFORMAÇÕES DO SISTEMA")
    info = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_executable": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "cwd": os.getcwd(),
        "pyserial_version": getattr(serial, "VERSION", "desconhecida"),
    }
    logger.write(json.dumps(info, ensure_ascii=False, indent=2))

    logger.section("VARIÁVEIS DE AMBIENTE RELEVANTES")
    interesting = [
        key
        for key in os.environ
        if key.upper() in {"PATH", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"}
        or key.upper().startswith(("PYTHON", "SERIAL"))
    ]
    for key in sorted(interesting):
        logger.write(f"{key}={os.environ.get(key)}")


def collect_os_usb_info(logger):
    logger.section("COMANDOS DO SISTEMA / USB / SERIAL")
    system = platform.system().lower()
    commands = []
    if system == "windows":
        commands = [
            ["where", "python"],
            ["python", "-m", "pip", "show", "pyserial"],
            ["mode"],
            ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_SerialPort | Format-List *"],
            ["powershell", "-NoProfile", "-Command", "Get-PnpDevice -Class Ports | Format-List *"],
            ["powershell", "-NoProfile", "-Command", "Get-PnpDevice -Class USB | Format-Table -AutoSize"],
        ]
    elif system == "linux":
        commands = [
            ["which", "python3"],
            [sys.executable, "-m", "pip", "show", "pyserial"],
            ["uname", "-a"],
            ["dmesg", "--ctime"],
            ["lsusb"],
            ["udevadm", "info", "--export-db"],
        ]
    elif system == "darwin":
        commands = [
            ["which", "python3"],
            [sys.executable, "-m", "pip", "show", "pyserial"],
            ["system_profiler", "SPUSBDataType", "SPSerialATADataType"],
            ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
        ]
    else:
        logger.write(f"Sistema sem comandos específicos cadastrados: {platform.system()}")

    for command in commands:
        log_command(logger, command)


def list_ports(logger):
    logger.section("PORTAS SERIAIS DETECTADAS PELO PYSERIAL")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        logger.write("Nenhuma porta serial encontrada pelo pyserial.")
        return []

    for index, port in enumerate(ports, start=1):
        logger.write(f"PORTA #{index}")
        attrs = {
            "device": port.device,
            "name": port.name,
            "description": port.description,
            "hwid": port.hwid,
            "vid": f"0x{port.vid:04x}" if port.vid is not None else None,
            "pid": f"0x{port.pid:04x}" if port.pid is not None else None,
            "serial_number": port.serial_number,
            "location": port.location,
            "manufacturer": port.manufacturer,
            "product": port.product,
            "interface": port.interface,
        }
        logger.write(json.dumps(attrs, ensure_ascii=False, indent=2))
    return ports


def choose_ports(args, ports):
    if args.port:
        return [args.port]
    if args.auto:
        return [port.device for port in ports]
    return ["COM3"] if platform.system().lower() == "windows" else [p.device for p in ports[:1]]


def serial_status(ser):
    return {
        "is_open": ser.is_open,
        "name": ser.name,
        "in_waiting": ser.in_waiting,
        "out_waiting": ser.out_waiting,
        "cts": ser.cts,
        "dsr": ser.dsr,
        "ri": ser.ri,
        "cd": ser.cd,
        "rts": ser.rts,
        "dtr": ser.dtr,
    }


def decode_lines(buffer):
    text = buffer.decode("ascii", errors="replace")
    parts = re.split(r"\r\n|\n|\r", text)
    return parts[:-1], parts[-1].encode("ascii", errors="replace")


def read_port(logger, port_name, baudrate, duration):
    logger.section(f"TESTE DE LEITURA SERIAL: porta={port_name} baudrate={baudrate} duração={duration}s")
    stats = {
        "bytes": 0,
        "blocks": 0,
        "lines": 0,
        "valid_weight_lines": 0,
        "invalid_lines": 0,
        "serial_errors": 0,
        "max_gap_seconds": 0.0,
        "first_byte_at": None,
        "last_byte_at": None,
    }
    buffer = b""
    last_data_time = None
    started = time.monotonic()

    try:
        ser = serial.Serial(
            port=port_name,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0,
            write_timeout=1,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.write(f"FALHA AO ABRIR PORTA: {type(exc).__name__}: {exc!r}")
        logger.write(traceback.format_exc())
        return stats

    with ser:
        logger.write("Porta aberta.")
        logger.write("Status inicial: " + json.dumps(serial_status(ser), ensure_ascii=False))
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            logger.write("Buffers limpos.")
        except Exception as exc:  # noqa: BLE001
            logger.write(f"Falha ao limpar buffers: {type(exc).__name__}: {exc!r}")

        next_status = time.monotonic() + 5
        while time.monotonic() - started < duration:
            try:
                waiting = ser.in_waiting
                if waiting:
                    data = ser.read(waiting)
                    now = time.monotonic()
                    if last_data_time is not None:
                        stats["max_gap_seconds"] = max(stats["max_gap_seconds"], now - last_data_time)
                    last_data_time = now
                    stats["first_byte_at"] = stats["first_byte_at"] or timestamp()
                    stats["last_byte_at"] = timestamp()
                    stats["bytes"] += len(data)
                    stats["blocks"] += 1
                    logger.write(
                        f"BLOCO #{stats['blocks']}: {len(data)} bytes | hex={data.hex(' ')} | ascii={data.decode('ascii', errors='replace')!r}"
                    )
                    buffer += data
                    lines, buffer = decode_lines(buffer)
                    for line in lines:
                        stats["lines"] += 1
                        match = PADRAO_PESO.search(line)
                        if match:
                            stats["valid_weight_lines"] += 1
                            logger.write(f"LINHA VÁLIDA #{stats['valid_weight_lines']}: {line!r} peso={int(match.group(2))} status={match.group(1)}")
                        else:
                            stats["invalid_lines"] += 1
                            logger.write(f"LINHA INVÁLIDA #{stats['invalid_lines']}: {line!r}")

                if time.monotonic() >= next_status:
                    logger.write("Status periódico: " + json.dumps(serial_status(ser), ensure_ascii=False))
                    next_status += 5
                time.sleep(READ_POLL_SECONDS)
            except Exception as exc:  # noqa: BLE001
                stats["serial_errors"] += 1
                logger.write(f"ERRO DURANTE LEITURA: {type(exc).__name__}: {exc!r}")
                logger.write(traceback.format_exc())
                time.sleep(1)

        if buffer:
            logger.write(f"SOBRA NO BUFFER SEM QUEBRA DE LINHA: {buffer!r}")
        logger.write("Status final: " + json.dumps(serial_status(ser), ensure_ascii=False))

    logger.write("RESUMO DA PORTA: " + json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


def write_csv_summary(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "port",
                "baudrate",
                "duration_seconds",
                "bytes",
                "blocks",
                "lines",
                "valid_weight_lines",
                "invalid_lines",
                "serial_errors",
                "max_gap_seconds",
                "first_byte_at",
                "last_byte_at",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Gera um log completo para comparar a leitura da balança em dois computadores."
    )
    parser.add_argument("--port", help="porta serial a testar, exemplo: COM3")
    parser.add_argument("--auto", action="store_true", help="testa todas as portas seriais detectadas")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="baudrate da balança")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="segundos de leitura por porta")
    parser.add_argument("--log", help="caminho do arquivo de log")
    parser.add_argument("--skip-system-commands", action="store_true", help="não executa comandos do sistema")
    return parser.parse_args()


def main():
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hostname = re.sub(r"[^A-Za-z0-9_.-]+", "_", socket.gethostname())
    log_path = Path(args.log or f"debug2_{hostname}_{stamp}.log")
    csv_path = log_path.with_suffix(".csv")
    logger = Logger(log_path)

    logger.section("INÍCIO DO DEBUG2 DA BALANÇA")
    logger.write(f"Arquivo de log: {log_path.resolve()}")
    logger.write(f"Arquivo CSV resumo: {csv_path.resolve()}")
    logger.write("Rode este script nos dois computadores com a mesma balança/cabo/adaptador, se possível.")
    logger.write("Depois envie o .log e o .csv de cada computador para comparação.")

    collect_system_info(logger)
    ports = list_ports(logger)
    if not args.skip_system_commands:
        collect_os_usb_info(logger)

    selected_ports = choose_ports(args, ports)
    logger.section("PORTAS SELECIONADAS PARA TESTE")
    logger.write(", ".join(selected_ports) if selected_ports else "Nenhuma porta selecionada.")

    rows = []
    for port_name in selected_ports:
        stats = read_port(logger, port_name, args.baudrate, args.duration)
        rows.append({
            "port": port_name,
            "baudrate": args.baudrate,
            "duration_seconds": args.duration,
            **stats,
        })

    write_csv_summary(csv_path, rows)
    logger.section("FIM DO DEBUG2")
    logger.write(f"Log gerado: {log_path.resolve()}")
    logger.write(f"Resumo CSV gerado: {csv_path.resolve()}")


if __name__ == "__main__":
    main()
