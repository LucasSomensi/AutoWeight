import serial
import time
import re
from datetime import datetime
from serial import SerialException

PORTA = "COM3"
BAUDRATE = 9600

INTERVALO_IMPRESSAO = 5
TEMPO_SEM_DADOS_PARA_RECONECTAR = 15

PADRAO_PESO = re.compile(r"(ST|US),GS,([+-]\d+)kg")

ultimo_peso = None
ultimo_print = 0
ultimo_dado_recebido = time.time()
buffer = ""


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar():
    while True:
        try:
            print(f"[{agora()}] Abrindo {PORTA}...")
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

            ser.reset_input_buffer()
            ser.reset_output_buffer()

            print(f"[{agora()}] Conectado.")
            return ser

        except Exception as e:
            print(f"[{agora()}] Erro ao conectar: {repr(e)}")
            time.sleep(5)


def extrair_peso(linha):
    match = PADRAO_PESO.search(linha)

    if not match:
        return None

    estabilidade = match.group(1)
    peso = int(match.group(2))

    return estabilidade, peso


ser = conectar()

print(f"[{agora()}] Lendo balança. Ctrl+C para parar.")

try:
    while True:
        try:
            n = ser.in_waiting

            if n > 0:
                dados = ser.read(n)
                ultimo_dado_recebido = time.time()

                texto = dados.decode("ascii", errors="replace")
                buffer += texto

                # Divide em linhas completas
                while "\n" in buffer or "\r" in buffer:
                    buffer = buffer.replace("\r", "\n")
                    partes = buffer.split("\n")

                    linhas_completas = partes[:-1]
                    buffer = partes[-1]

                    for linha in linhas_completas:
                        linha = linha.strip()

                        if not linha:
                            continue

                        resultado = extrair_peso(linha)

                        if resultado is None:
                            print(f"[{agora()}] Linha ignorada: {repr(linha)}")
                            continue

                        estabilidade, peso = resultado

                        agora_time = time.time()

                        if peso != ultimo_peso and agora_time - ultimo_print >= INTERVALO_IMPRESSAO:
                            print(f"[{agora()}] Peso: {peso} kg | status: {estabilidade}")
                            ultimo_peso = peso
                            ultimo_print = agora_time

            # Se ficou tempo demais sem receber nada, tenta reabrir a porta
            tempo_sem_dados = time.time() - ultimo_dado_recebido

            if tempo_sem_dados > TEMPO_SEM_DADOS_PARA_RECONECTAR:
                print(f"[{agora()}] Sem dados há {tempo_sem_dados:.1f}s. Reabrindo porta...")

                try:
                    ser.close()
                except:
                    pass

                time.sleep(2)
                ser = conectar()

                ultimo_dado_recebido = time.time()
                buffer = ""

            time.sleep(0.05)

        except SerialException as e:
            print(f"[{agora()}] Erro serial: {repr(e)}. Reconectando...")

            try:
                ser.close()
            except:
                pass

            time.sleep(2)
            ser = conectar()
            ultimo_dado_recebido = time.time()
            buffer = ""

except KeyboardInterrupt:
    print(f"[{agora()}] Encerrando...")

finally:
    try:
        ser.close()
    except:
        pass