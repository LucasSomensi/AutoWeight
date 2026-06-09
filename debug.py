import serial
import serial.tools.list_ports
import time
import traceback
from datetime import datetime

# =========================
# CONFIGURAÇÃO
# =========================

PORTA = "COM3"       # troque pela porta correta
BAUDRATE = 9600
ARQUIVO_LOG = "debug_balanca.log"

# Tempo total entre leituras principais
INTERVALO_SEGUNDOS = 5

# Quanto tempo o script tenta observar dados em cada ciclo
JANELA_LEITURA_SEGUNDOS = 2

# =========================
# FUNÇÕES
# =========================

def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def log(msg):
    linha = f"[{agora()}] {msg}"
    print(linha)

    with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def listar_portas():
    log("=== PORTAS SERIAIS DETECTADAS ===")

    portas = list(serial.tools.list_ports.comports())

    if not portas:
        log("Nenhuma porta serial encontrada.")
        return

    for p in portas:
        log(f"Porta: {p.device}")
        log(f"  descrição: {p.description}")
        log(f"  hwid: {p.hwid}")
        log(f"  fabricante: {p.manufacturer}")
        log(f"  produto: {p.product}")
        log(f"  serial_number: {p.serial_number}")


def conectar():
    log(f"Tentando abrir porta {PORTA} em {BAUDRATE} bps...")

    ser = serial.Serial(
        port=PORTA,
        baudrate=BAUDRATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
        write_timeout=1,
        rtscts=False,
        dsrdtr=False,
        xonxoff=False
    )

    log("Porta aberta com sucesso.")
    log(f"is_open: {ser.is_open}")
    log(f"name: {ser.name}")
    log(f"in_waiting inicial: {ser.in_waiting}")

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        log("Buffers limpos com reset_input_buffer/reset_output_buffer.")
    except Exception as e:
        log(f"Erro ao limpar buffers: {repr(e)}")

    return ser


def mostrar_status_serial(ser):
    try:
        log(
            "STATUS SERIAL | "
            f"is_open={ser.is_open} | "
            f"in_waiting={ser.in_waiting} | "
            f"out_waiting={ser.out_waiting} | "
            f"CTS={ser.cts} | "
            f"DSR={ser.dsr} | "
            f"RI={ser.ri} | "
            f"CD={ser.cd}"
        )
    except Exception as e:
        log(f"Erro ao ler status serial: {repr(e)}")


def diagnosticar_leitura(ser):
    """
    Observa a porta por alguns segundos e registra tudo que chegar:
    - quantidade de bytes
    - bytes crus
    - hexadecimal
    - tentativa de texto ASCII
    """

    inicio = time.time()
    total_bytes = 0
    blocos = 0

    log(f"Iniciando janela de leitura de {JANELA_LEITURA_SEGUNDOS} segundos...")
    mostrar_status_serial(ser)

    while time.time() - inicio < JANELA_LEITURA_SEGUNDOS:
        try:
            n = ser.in_waiting

            if n > 0:
                dados = ser.read(n)
                total_bytes += len(dados)
                blocos += 1

                log(f"BLOCO RECEBIDO #{blocos}")
                log(f"  bytes: {len(dados)}")
                log(f"  raw repr: {repr(dados)}")
                log(f"  hex: {dados.hex(' ')}")

                try:
                    texto = dados.decode("ascii", errors="replace")
                    log(f"  ascii: {repr(texto)}")
                except Exception as e:
                    log(f"  erro decode ascii: {repr(e)}")

            time.sleep(0.05)

        except Exception as e:
            log("ERRO DURANTE LEITURA")
            log(f"Tipo: {type(e).__name__}")
            log(f"Erro: {repr(e)}")
            log(traceback.format_exc())
            raise

    log(f"Fim da janela. Total recebido: {total_bytes} bytes em {blocos} blocos.")
    mostrar_status_serial(ser)

    return total_bytes


# =========================
# PROGRAMA PRINCIPAL
# =========================

def main():
    with open(ARQUIVO_LOG, "w", encoding="utf-8") as f:
        f.write("")

    log("======================================")
    log("INÍCIO DO DEBUG DA BALANÇA")
    log("======================================")
    log(f"PORTA configurada: {PORTA}")
    log(f"BAUDRATE configurado: {BAUDRATE}")
    log(f"INTERVALO_SEGUNDOS: {INTERVALO_SEGUNDOS}")
    log(f"JANELA_LEITURA_SEGUNDOS: {JANELA_LEITURA_SEGUNDOS}")

    listar_portas()

    ser = None
    ultimo_total = None
    ciclos_sem_dados = 0

    try:
        ser = conectar()

        ciclo = 0

        while True:
            ciclo += 1
            log("--------------------------------------")
            log(f"CICLO {ciclo}")

            try:
                total = diagnosticar_leitura(ser)

                if total == 0:
                    ciclos_sem_dados += 1
                    log(f"Nenhum dado recebido neste ciclo. Ciclos seguidos sem dados: {ciclos_sem_dados}")
                else:
                    ciclos_sem_dados = 0
                    log("Dados recebidos neste ciclo.")

                if ultimo_total is not None and total == ultimo_total:
                    log(f"Total de bytes igual ao ciclo anterior: {total}")
                else:
                    log(f"Total de bytes mudou em relação ao ciclo anterior: anterior={ultimo_total}, atual={total}")

                ultimo_total = total

            except Exception:
                log("Falha no ciclo de leitura. Tentando reconectar...")

                try:
                    if ser:
                        ser.close()
                        log("Porta fechada após erro.")
                except Exception as e:
                    log(f"Erro ao fechar porta após falha: {repr(e)}")

                time.sleep(2)

                try:
                    ser = conectar()
                    ciclos_sem_dados = 0
                    log("Reconexão feita.")
                except Exception as e:
                    log("Erro ao reconectar.")
                    log(f"Tipo: {type(e).__name__}")
                    log(f"Erro: {repr(e)}")
                    log(traceback.format_exc())

            log(f"Aguardando {INTERVALO_SEGUNDOS} segundos até próximo ciclo...")
            time.sleep(INTERVALO_SEGUNDOS)

    except KeyboardInterrupt:
        log("Interrompido pelo usuário com Ctrl+C.")

    except Exception as e:
        log("ERRO FATAL")
        log(f"Tipo: {type(e).__name__}")
        log(f"Erro: {repr(e)}")
        log(traceback.format_exc())

    finally:
        try:
            if ser:
                ser.close()
                log("Porta serial fechada no finally.")
        except Exception as e:
            log(f"Erro ao fechar porta no finally: {repr(e)}")

        log("======================================")
        log("FIM DO DEBUG")
        log("======================================")


if __name__ == "__main__":
    main()