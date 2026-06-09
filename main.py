import csv
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import serial
from serial import SerialException

PORTA = "COM3"
BAUDRATE = 9600

INTERVALO_IMPRESSAO = 5
TEMPO_SEM_DADOS_PARA_RECONECTAR = 15

LIMITE_PESO_KG = 1000
TEMPO_ESTABILIDADE_SEGUNDOS = 10
OSCILACAO_MAXIMA_KG = 20
PESO_RESET_KG = 300
ARQUIVO_CSV = Path("pesagens.csv")

PADRAO_PESO = re.compile(r"(ST|US),GS,([+-]\d+)kg")

ultimo_peso_impresso = None
ultimo_print = 0
ultimo_dado_recebido = time.time()
buffer = ""

amostras_estabilidade = deque()
peso_candidato = None
inicio_peso_candidato = None
pesagem_registrada = False


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
                xonxoff=False,
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

    status_balanca = match.group(1)
    peso = int(match.group(2))

    return status_balanca, peso


def registrar_pesagem_csv(ultima_leitura, amostras):
    ARQUIVO_CSV.parent.mkdir(parents=True, exist_ok=True)
    arquivo_existe = ARQUIVO_CSV.exists() and ARQUIVO_CSV.stat().st_size > 0

    pesos = [peso_amostra for _, peso_amostra in amostras]
    peso_minimo = min(pesos)
    peso_maximo = max(pesos)
    oscilacao = peso_maximo - peso_minimo
    peso_medido = round(sum(pesos) / len(pesos))

    with ARQUIVO_CSV.open("a", newline="", encoding="utf-8") as arquivo:
        campos = [
            "data_hora",
            "peso_kg",
            "ultima_leitura_kg",
            "peso_minimo_janela_kg",
            "peso_maximo_janela_kg",
            "oscilacao_janela_kg",
            "tempo_estabilidade_s",
        ]
        writer = csv.DictWriter(arquivo, fieldnames=campos)

        if not arquivo_existe:
            writer.writeheader()

        writer.writerow(
            {
                "data_hora": agora(),
                "peso_kg": peso_medido,
                "ultima_leitura_kg": ultima_leitura,
                "peso_minimo_janela_kg": peso_minimo,
                "peso_maximo_janela_kg": peso_maximo,
                "oscilacao_janela_kg": oscilacao,
                "tempo_estabilidade_s": TEMPO_ESTABILIDADE_SEGUNDOS,
            }
        )

    print(
        f"[{agora()}] Pesagem registrada em {ARQUIVO_CSV}: "
        f"{peso_medido} kg | última leitura: {ultima_leitura} kg | "
        f"oscilação na janela: {oscilacao} kg"
    )


def limpar_candidato():
    global peso_candidato, inicio_peso_candidato

    peso_candidato = None
    inicio_peso_candidato = None
    amostras_estabilidade.clear()


def avaliar_pesagem(peso):
    global pesagem_registrada, peso_candidato, inicio_peso_candidato

    timestamp_atual = time.time()

    if pesagem_registrada:
        if peso < PESO_RESET_KG:
            pesagem_registrada = False
            limpar_candidato()
            print(
                f"[{agora()}] Peso caiu para {peso} kg. "
                "Sistema liberado para nova pesagem."
            )
        return

    if peso <= LIMITE_PESO_KG:
        if peso_candidato is not None:
            print(
                f"[{agora()}] Peso voltou para {peso} kg antes de estabilizar. "
                "Aguardando nova entrada acima do limite."
            )
        limpar_candidato()
        return

    if peso_candidato is None:
        peso_candidato = peso
        inicio_peso_candidato = timestamp_atual
        amostras_estabilidade.append((timestamp_atual, peso))
        print(
            f"[{agora()}] Peso acima de {LIMITE_PESO_KG} kg. "
            f"Candidato estável iniciado em {peso_candidato} kg."
        )
        return

    if abs(peso - peso_candidato) <= OSCILACAO_MAXIMA_KG:
        amostras_estabilidade.append((timestamp_atual, peso))
    else:
        print(
            f"[{agora()}] Peso {peso} kg saiu da faixa do candidato "
            f"{peso_candidato} kg (+/- {OSCILACAO_MAXIMA_KG} kg). "
            "Reiniciando cronômetro de estabilidade."
        )
        peso_candidato = peso
        inicio_peso_candidato = timestamp_atual
        amostras_estabilidade.clear()
        amostras_estabilidade.append((timestamp_atual, peso))
        return

    duracao_candidato = timestamp_atual - inicio_peso_candidato

    if duracao_candidato >= TEMPO_ESTABILIDADE_SEGUNDOS:
        registrar_pesagem_csv(peso, list(amostras_estabilidade))
        pesagem_registrada = True
        limpar_candidato()
        print(
            f"[{agora()}] Aguardando peso cair abaixo de {PESO_RESET_KG} kg "
            "para liberar a próxima pesagem."
        )


def processar_linha(linha):
    global ultimo_peso_impresso, ultimo_print

    resultado = extrair_peso(linha)

    if resultado is None:
        print(f"[{agora()}] Linha ignorada: {repr(linha)}")
        return

    status_balanca, peso = resultado
    agora_time = time.time()

    if peso != ultimo_peso_impresso and agora_time - ultimo_print >= INTERVALO_IMPRESSAO:
        print(
            f"[{agora()}] Peso: {peso} kg | status recebido: {status_balanca} "
            "| estabilidade calculada por faixa candidata"
        )
        ultimo_peso_impresso = peso
        ultimo_print = agora_time

    avaliar_pesagem(peso)


def processar_buffer():
    global buffer

    while "\n" in buffer or "\r" in buffer:
        buffer = buffer.replace("\r", "\n")
        partes = buffer.split("\n")

        linhas_completas = partes[:-1]
        buffer = partes[-1]

        for linha in linhas_completas:
            linha = linha.strip()

            if not linha:
                continue

            processar_linha(linha)


def reconectar(ser, motivo):
    global ultimo_dado_recebido, buffer

    print(f"[{agora()}] {motivo}. Reabrindo porta...")

    try:
        ser.close()
    except Exception:
        pass

    time.sleep(2)
    novo_ser = conectar()

    ultimo_dado_recebido = time.time()
    buffer = ""

    return novo_ser


def main():
    global ultimo_dado_recebido, buffer

    ser = conectar()

    print(f"[{agora()}] Lendo balança. Ctrl+C para parar.")
    print(
        f"[{agora()}] MVP ativo: registra em {ARQUIVO_CSV} quando peso > "
        f"{LIMITE_PESO_KG} kg e permanece dentro de +/- "
        f"{OSCILACAO_MAXIMA_KG} kg do candidato por "
        f"{TEMPO_ESTABILIDADE_SEGUNDOS}s."
    )

    try:
        while True:
            try:
                n = ser.in_waiting

                if n > 0:
                    dados = ser.read(n)
                    ultimo_dado_recebido = time.time()

                    texto = dados.decode("ascii", errors="replace")
                    buffer += texto

                    processar_buffer()

                tempo_sem_dados = time.time() - ultimo_dado_recebido

                if tempo_sem_dados > TEMPO_SEM_DADOS_PARA_RECONECTAR:
                    ser = reconectar(
                        ser,
                        f"Sem dados há {tempo_sem_dados:.1f}s",
                    )

                time.sleep(0.05)

            except SerialException as e:
                ser = reconectar(ser, f"Erro serial: {repr(e)}")

    except KeyboardInterrupt:
        print(f"[{agora()}] Encerrando...")

    finally:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
