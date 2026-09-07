import argparse
import re
import sys
import time
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import serial
import numpy as np
from serial import SerialException

from camera import Camera, carregar_url, salvar_jpeg

PORTA = "COM5"
BAUDRATE = 9600

INTERVALO_IMPRESSAO = 5
TEMPO_SEM_DADOS_PARA_RECONECTAR = 15

LIMITE_PESO_KG = 1000
TEMPO_ESTABILIDADE_SEGUNDOS = 5
OSCILACAO_MAXIMA_KG = 20
PESO_RESET_KG = 300
PASTA_DADOS = Path(__file__).resolve().parent / "AutoWeightData"

PADRAO_PESO = re.compile(r"(ST|US),GS,([+-]\d+)kg")

modo_verbose = False
ultimo_peso_impresso = None
ultimo_print = 0
ultimo_dado_recebido = time.time()
buffer = ""

amostras_estabilidade = deque()
peso_candidato = None
inicio_peso_candidato = None
pesagem_registrada = False
ultima_pesagem_registrada_kg = None
camera = None
ultima_foto = None
ultima_tentativa_foto = float("-inf")
parar = threading.Event()
estado_lock = threading.Lock()
estado = {"peso": None, "recebido": None, "foto": None,
          "hora": None, "peso_foto": None, "foto_branca": False,
          "mensagem": "Iniciando…"}


def atualizar_estado(**valores):
    with estado_lock:
        estado.update(valores)


def obter_estado():
    with estado_lock:
        return estado.copy()


def configurar_argumentos():
    parser = argparse.ArgumentParser(
        description="Lê pesos enviados pela balança serial e registra pesagens estáveis."
    )
    parser.add_argument(
        "-verbose",
        "--verbose",
        action="store_true",
        help=(
            "lista todos os pesos válidos recebidos da balança, sem aplicar "
            "o filtro de intervalo/mudança usado na saída padrão"
        ),
    )
    parser.add_argument("--sem-gui", action="store_true", help="executa apenas no terminal")
    return parser.parse_args()


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar():
    while not parar.is_set():
        try:
            atualizar_estado(mensagem=f"Conectando à balança ({PORTA})…", peso=None)
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
            atualizar_estado(mensagem="Aguardando peso da balança…")
            return ser

        except Exception as e:
            print(f"[{agora()}] Erro ao conectar: {repr(e)}")
            atualizar_estado(mensagem=f"Balança indisponível ({PORTA}). Tentando reconectar…", peso=None)
            parar.wait(5)


def extrair_peso(linha):
    match = PADRAO_PESO.search(linha)

    if not match:
        return None

    status_balanca = match.group(1)
    peso = int(match.group(2))

    return status_balanca, peso


def registrar_pesagem_foto(amostras, substituir_ultima=False):
    global ultima_foto, ultima_tentativa_foto

    if time.monotonic() - ultima_tentativa_foto < 3:
        return None
    ultima_tentativa_foto = time.monotonic()
    peso_maximo = max(peso for _, peso in amostras)
    horario = datetime.now()
    nome = horario.strftime("%Y-%m-%d-%H-%M-%S-%f")
    destino = PASTA_DADOS / f"{nome}-{peso_maximo}kg.jpg"
    foto_branca = False
    try:
        frame = camera.foto_recente() if camera is not None else None
        if frame is None:
            raise RuntimeError("Sem imagem recente da câmera")
        salvar_jpeg(frame, destino)
    except Exception as erro:
        foto_branca = True
        print(f"[{agora()}] Foto indisponível ({type(erro).__name__}); "
              "registrando imagem em branco.")
        try:
            salvar_jpeg(np.full((1080, 1920, 3), 255, dtype=np.uint8), destino)
        except Exception as erro_branco:
            atualizar_estado(mensagem="Falha ao salvar a pesagem. Nova tentativa em breve.")
            print(f"[{agora()}] Não foi possível gravar a imagem em branco "
                  f"({type(erro_branco).__name__}). "
                  "Pesagem ainda não registrada; haverá nova tentativa.")
            return None

    anterior = ultima_foto
    ultima_foto = destino
    atualizar_estado(foto=destino, hora=horario, peso_foto=peso_maximo,
                     foto_branca=foto_branca, mensagem="Pesagem registrada.")
    if substituir_ultima and anterior is not None:
        try:
            anterior.unlink(missing_ok=True)
        except OSError:
            print(f"[{agora()}] Foto nova salva, mas a anterior não pôde ser removida: {anterior.name}")
    print(f"[{agora()}] Pesagem registrada: {destino}")
    return peso_maximo


def limpar_candidato():
    global peso_candidato, inicio_peso_candidato

    peso_candidato = None
    inicio_peso_candidato = None
    amostras_estabilidade.clear()


def avaliar_pesagem(peso):
    global pesagem_registrada, peso_candidato, inicio_peso_candidato
    global ultima_pesagem_registrada_kg

    timestamp_atual = time.time()
    substituir_ultima = False

    if pesagem_registrada:
        if peso < PESO_RESET_KG:
            pesagem_registrada = False
            ultima_pesagem_registrada_kg = None
            limpar_candidato()
            print(
                f"[{agora()}] Peso caiu para {peso} kg. "
                "Sistema liberado para nova pesagem."
            )
            return

        if (
            ultima_pesagem_registrada_kg is None
            or peso <= ultima_pesagem_registrada_kg
        ):
            limpar_candidato()
            return

        substituir_ultima = True

    elif peso <= LIMITE_PESO_KG:
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

        if substituir_ultima:
            print(
                f"[{agora()}] Peso acima do último registro "
                f"({ultima_pesagem_registrada_kg} kg). "
                f"Candidato de substituição iniciado em {peso_candidato} kg."
            )
        else:
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
        peso_registrado = registrar_pesagem_foto(
            list(amostras_estabilidade),
            substituir_ultima=substituir_ultima,
        )
        if peso_registrado is None:
            return
        ultima_pesagem_registrada_kg = peso_registrado
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
    atualizar_estado(peso=peso, recebido=time.monotonic(), mensagem="Recebendo peso da balança")
    agora_time = time.time()

    if modo_verbose:
        print(
            f"[{agora()}] Peso recebido: {peso} kg | status recebido: "
            f"{status_balanca}"
        )
    elif peso != ultimo_peso_impresso and agora_time - ultimo_print >= INTERVALO_IMPRESSAO:
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

    limpar_candidato()
    atualizar_estado(peso=None, mensagem="Reconectando à balança…")
    parar.wait(2)
    novo_ser = conectar()

    ultimo_dado_recebido = time.time()
    buffer = ""

    return novo_ser


def executar(verbose=False):
    global ultimo_dado_recebido, buffer, modo_verbose, camera

    modo_verbose = verbose
    ser = None

    try:
        camera = Camera(carregar_url())
        PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    except (RuntimeError, OSError) as erro:
        print(f"[{agora()}] {erro}")
        atualizar_estado(mensagem=str(erro))
        return

    camera.start()

    print(f"[{agora()}] Lendo balança. Ctrl+C para parar.")
    if modo_verbose:
        print(f"[{agora()}] Modo verbose ativo: listando todos os pesos recebidos.")

    print(
        f"[{agora()}] Registro por foto ativo: salva em {PASTA_DADOS} quando peso > "
        f"{LIMITE_PESO_KG} kg e permanece dentro de +/- "
        f"{OSCILACAO_MAXIMA_KG} kg do candidato por "
        f"{TEMPO_ESTABILIDADE_SEGUNDOS}s."
    )

    try:
        ser = conectar()
        ultimo_dado_recebido = time.time()
        while not parar.is_set() and ser is not None:
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

                parar.wait(0.05)

            except SerialException as e:
                ser = reconectar(ser, f"Erro serial: {repr(e)}")

    except KeyboardInterrupt:
        print(f"[{agora()}] Encerrando...")

    except Exception as erro:
        atualizar_estado(peso=None, mensagem=f"Leitura interrompida: {type(erro).__name__}. Reinicie o programa.")
        print(f"[{agora()}] Leitura interrompida: {erro!r}")

    finally:
        camera.close()
        try:
            ser.close()
        except Exception:
            pass


def main():
    args = configurar_argumentos()
    if args.sem_gui:
        executar(args.verbose)
    else:
        from gui import iniciar
        iniciar(sys.modules[__name__], args.verbose)


if __name__ == "__main__":
    main()
