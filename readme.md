# Leitor Serial de Balança Rodoviária

Projeto em Python para ler dados enviados por uma balança rodoviária conectada ao computador via USB/serial a fim de automatizar sua operação parcialmente.

A balança aparece no Windows como:

```text
FT232R USB UART
USB Serial Port (COM3)
```

A porta correta identificada é:

```text
COM3
```

O objetivo inicial do projeto é criar um leitor confiável para capturar o peso enviado pela balança, imprimir apenas mudanças relevantes e lidar melhor com possíveis interrupções na comunicação serial.

---

## Contexto do hardware

A balança está conectada ao computador via USB usando um conversor FTDI, identificado como:

```text
USB VID:PID=0403:6001
Fabricante: FTDI
Descrição: USB Serial Port (COM3)
```

A comunicação funcionou corretamente com os seguintes parâmetros:

```text
Porta: COM3
Baudrate: 9600
Data bits: 8
Parity: None
Stop bits: 1
Flow control: desativado
```

Em termos pyserial:

```python
serial.Serial(
    port="COM3",
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1
)
```

---

## Formato dos dados recebidos

A balança envia linhas ASCII terminadas por `\r\n`.

Exemplos reais observados:

```text
ST,GS,+0000000kg
ST,GS,+0001260kg
US,GS,+0001260kg
ST,GS,+0002200kg
```

Interpretação provável:

```text
ST = stable / peso estável
US = unstable / peso instável
GS = gross weight / peso bruto
+0002200kg = peso em kg
```

Exemplo:

```text
ST,GS,+0002200kg
```

Provavelmente significa:

```text
Peso estável bruto: 2200 kg
```

Regex sugerido para parse:

```python
r"(ST|US),GS,([+-]\d+)kg"
```

---

## Problema observado

Scripts simples usando `readline()` funcionaram inicialmente, mas depois pareciam “travar” ou parar de receber dados.

Um script de debug mostrou que:

1. A porta `COM3` abre corretamente.
2. A balança transmite dados continuamente no início.
3. Os dados chegam em blocos completos ou parcialmente quebrados.
4. Depois de algum tempo, o script continua rodando e a porta continua aberta, mas nenhum byte novo chega.
5. Não aparecem erros como `SerialException`, `PermissionError` ou perda explícita da porta COM.

Conclusão provável:

> O Python não está necessariamente travando. O fluxo de dados da balança/indicador parece parar de chegar pela serial.

Isso pode ser causado por:

* configuração do indicador da balança;
* modo de transmissão não contínuo;
* modo standby/economia;
* transmissão somente em certas condições;
* ruído/interferência elétrica;
* problema físico no cabo/conversor USB;
* controle RTS/DTR ou estado da porta afetando o indicador.

---

## Cuidados importantes no código

### Não depender cegamente de `readline()`

Embora os pacotes terminem em `\r\n`, o log mostrou que os dados podem chegar quebrados em blocos parciais, por exemplo:

```text
ST,GS,+000
0000kg\r\n
```

ou:

```text
ST
,GS,+0000000kg\r\n
```

Portanto, o leitor ideal deve:

1. Ler bytes disponíveis com `read()` ou `read_all()`.
2. Acumular em um buffer.
3. Separar linhas completas por `\r`/`\n`.
4. Ignorar linhas incompletas até que sejam completadas.
5. Aplicar regex somente em linhas completas.

---

## Objetivos do projeto

### Versão mínima

Criar um script que:

* abra a porta `COM3`;
* leia dados da balança;
* extraia o peso;
* imprima o peso apenas quando houver mudança;
* mostre se o peso está estável (`ST`) ou instável (`US`).

### Versão robusta

Criar um serviço/script que:

* reconecte automaticamente se a porta cair;
* detecte quando a porta está aberta, mas sem receber dados;
* reabra a porta após X segundos sem dados;
* gere logs úteis para diagnóstico;
* salve leituras em arquivo CSV ou banco de dados;
* aceite configuração via arquivo `.env`, `.toml`, `.yaml` ou argumentos CLI;
* funcione bem no Windows.

---

## Dependências

Instalar:

```bash
pip install pyserial
```

Opcional para desenvolvimento:

```bash
pip install pytest
```

---

## Exemplo de leitura/parsing

```python
import re

PADRAO_PESO = re.compile(r"(ST|US),GS,([+-]\d+)kg")

def extrair_peso(linha: str):
    match = PADRAO_PESO.search(linha)

    if not match:
        return None

    status = match.group(1)
    peso = int(match.group(2))

    return {
        "status": status,
        "estavel": status == "ST",
        "peso_kg": peso,
    }


print(extrair_peso("ST,GS,+0002200kg"))
```

Saída esperada:

```python
{
    "status": "ST",
    "estavel": True,
    "peso_kg": 2200
}
```

---

## Script base sugerido

```python
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

    estabilidade = match.group(1)
    peso = int(match.group(2))

    return estabilidade, peso


def main():
    global ultimo_peso
    global ultimo_print
    global ultimo_dado_recebido
    global buffer

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

                    buffer = buffer.replace("\r", "\n")

                    while "\n" in buffer:
                        linha, buffer = buffer.split("\n", 1)
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

                tempo_sem_dados = time.time() - ultimo_dado_recebido

                if tempo_sem_dados > TEMPO_SEM_DADOS_PARA_RECONECTAR:
                    print(f"[{agora()}] Sem dados há {tempo_sem_dados:.1f}s. Reabrindo porta...")

                    try:
                        ser.close()
                    except Exception:
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
                except Exception:
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
        except Exception:
            pass


if __name__ == "__main__":
    main()
```

---

## Debug realizado

Foi criado um script de diagnóstico que gerou um log com os seguintes achados:

### Porta identificada

```text
Porta: COM3
descrição: USB Serial Port (COM3)
hwid: USB VID:PID=0403:6001 SER=A9O5HZZNA
fabricante: FTDI
```

### Dados recebidos

Exemplo real:

```text
ST,GS,+0000000kg\r\n
```

Também foram observados pacotes acumulados:

```text
ST,GS,+0000000kg\r\nST,GS,+0000000kg\r\n...
```

E pacotes quebrados:

```text
ST,GS,+000
0000kg\r\n
```

### Sintoma principal

Depois de um período funcionando, a porta continuava aberta, mas a leitura passava a retornar:

```text
Total recebido: 0 bytes em 0 blocos
```

Sem erro serial explícito.

---

## Próximas tarefas sugeridas para o Codex

1. Transformar o script em um pacote Python simples.
2. Separar responsabilidades:

   * `serial_reader.py`
   * `parser.py`
   * `logger.py`
   * `main.py`
3. Criar testes unitários para o parser.
4. Criar teste com pacotes quebrados.
5. Criar configuração externa para porta/baudrate.
6. Criar modo debug.
7. Criar logs rotativos.
8. Criar saída CSV.
9. Criar opção para imprimir apenas pesos estáveis (`ST`).
10. Investigar comportamento de reconexão quando a porta fica aberta mas para de receber bytes.

---

## Testes unitários desejáveis

Casos para o parser:

```python
"ST,GS,+0000000kg" -> 0 kg, estável
"US,GS,+0001260kg" -> 1260 kg, instável
"ST,GS,+0002200kg" -> 2200 kg, estável
"lixo" -> None
"" -> None
```

Casos para buffer:

```python
["ST,GS,+000", "2200kg\r\n"] -> "ST,GS,+0002200kg"
["ST", ",GS,+0002200kg\r\n"] -> "ST,GS,+0002200kg"
["ST,GS,+0000000kg\r\nST,GS,+0001260kg\r\n"] -> duas leituras
```

---

## Observações operacionais

Se o script parar de receber dados, testar fisicamente:

1. mexer no peso da balança;
2. apertar `Print`, `Zero`, `Tara` ou tecla equivalente no indicador;
3. verificar se a transmissão volta;
4. testar outro cabo USB;
5. testar outra porta USB;
6. desabilitar economia de energia USB no Windows;
7. verificar no menu do indicador se a saída serial está configurada como contínua.

Configuração desejada no indicador, se existir:

```text
RS232 / Serial output: Continuous
Baudrate: 9600
Data bits: 8
Parity: None
Stop bits: 1
Protocol: ASCII
```

---

## Estado atual

* Porta correta: `COM3`
* Baudrate funcional: `9600`
* Protocolo observado: ASCII com linhas terminadas em `\r\n`
* Formato observado: `ST,GS,+0000000kg`
* Problema em aberto: a comunicação para de receber bytes sem erro explícito na porta serial

---

## MVP atual: registro local de pesagens estabilizadas

O script principal continua lendo a balança pela serial e interpretando linhas no formato já observado, como:

```text
ST,GS,+0002200kg
US,GS,+0002200kg
```

Para este MVP, o status `ST`/`US` recebido da balança é usado apenas para diagnóstico no console. A decisão de estabilidade não confia nesse status.

A regra implementada é:

1. Quando o peso fica acima de `1000 kg`, o script começa a observar as leituras.
2. O peso só é considerado estabilizado quando, durante uma janela contínua de `10 segundos`, a diferença entre a menor e a maior leitura for de no máximo `20 kg`.
3. Ao estabilizar, o script registra uma linha no arquivo local `pesagens.csv` com data/hora, peso medido e dados da janela de estabilidade.
4. Para evitar registros repetidos do mesmo caminhão, o sistema só libera uma nova pesagem depois que o peso cair abaixo de `300 kg`.

Campos gravados no CSV:

```text
data_hora,peso_kg,ultima_leitura_kg,peso_minimo_janela_kg,peso_maximo_janela_kg,oscilacao_janela_kg,tempo_estabilidade_s
```

O campo `peso_kg` é a média arredondada das leituras dentro da janela estável de 10 segundos. O campo `ultima_leitura_kg` mantém a última leitura recebida no momento do registro.
