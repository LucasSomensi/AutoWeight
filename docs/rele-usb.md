# Relé USB da sirene

## Identificação e teste

Em 05/10/2026, o Windows identificou o módulo como **USB-SERIAL CH340
(COM7)**, USB VID:PID **1A86:7523**. O teste enviou três pulsos de um segundo
ao canal 1 e Lucas confirmou que ouviu os cliques. O último comando foi
desligar. A sirene ainda não estava conectada; seu funcionamento não foi testado.

O módulo respondeu ao protocolo serial usado por módulos LCUS-1/HW-677.
O identificador CH340 identifica o conversor USB serial, não o modelo exato
da placa. Referência de implementação do protocolo:
[USB Controlled Relay LCUS-1](https://github.com/diyism/usb-controlled-relay-lcus1).

## Acionamento manual

Execute na pasta AutoWeight. O script usa `pyserial`, já presente em
`requirements.txt`.

```powershell
python -B relay_usb.py listar
python -B relay_usb.py teste --porta COM7
python -B relay_usb.py pulso --porta COM7 --segundos 2
python -B relay_usb.py ligar --porta COM7
python -B relay_usb.py desligar --porta COM7
```

`teste` executa três pulsos, com um segundo ligado e um segundo desligado.
`pulso` executa um pulso. Ambos enviam desligar também em `finally`, inclusive
ao interromper com Ctrl+C. `ligar` deixa o relé acionado até outro comando;
fechar a porta serial não envia desligar. Falta de energia, remoção do USB
ou encerramento forçado do processo podem impedir o comando final.

A porta pode mudar ao reconectar. Sem `--porta`, o script detecta
automaticamente o único dispositivo CH340 com VID:PID 1A86:7523.
Use `--porta` somente para escolher a porta manualmente.
O script verifica se a porta pertence a um CH340 com VID:PID 1A86:7523;
se houver outros CH340, identifique qual é o relé antes de comandá-lo.
A balança utiliza COM5 e o teste do relé não usa essa porta.

## Protocolo para integração

Configuração: **9600 baud, 8 bits, sem paridade, 1 stop bit (8N1)**,
sem controle de fluxo. Envie quatro bytes binários, sem texto, CR ou LF:

| Ação no canal 1 | Bytes hexadecimais |
| --- | --- |
| Ligar | `A0 01 01 A2` |
| Desligar | `A0 01 00 A1` |

```python
import time
import serial

with serial.Serial("COM7", 9600, timeout=0.5, write_timeout=2) as porta:
    try:
        porta.write(bytes.fromhex("A0 01 01 A2"))
        porta.flush()
        time.sleep(1)
    finally:
        porta.write(bytes.fromhex("A0 01 00 A1"))
        porta.flush()
```

A escrita bem-sucedida confirma envio pela serial, sem comprovar posição dos
contatos ou som da sirene. Neste teste, a resposta física foi confirmada pelos
cliques ouvidos. O script não exige uma resposta serial do módulo.

## Uso na automação

O **modo ausente** em `main.py` aciona o canal 1 por cinco segundos após o
primeiro registro salvo de cada caminhão, incluindo imagem de contingência.
Substituições por um peso maior não repetem o pulso. A próxima pesagem é
liberada quando o peso cai abaixo de 300 kg. Falhas ao gravar não acionam o
relé; a primeira gravação bem-sucedida pode acioná-lo.

Ative pelo botão na GUI ou pela tecla **A** no terminal Windows, sem Enter.
O modo inicia desativado e não é persistido. A tecla exige um terminal
interativo em foco. Ativá-lo depois do primeiro registro não gera pulso
retroativo. Desativá-lo impede novas solicitações, mas permite concluir as
já feitas.

`sirene.py` mantém uma thread dedicada e serializa os pulsos para não bloquear
a balança ou a interface. Antes de cada pulso, `localizar_rele()` identifica
o único dispositivo com VID:PID **1A86:7523** e usa sua porta COM atual.
Trocar a entrada USB ou reconectar não exige configuração nem reinício.
Nenhum dispositivo correspondente ou mais de um produz uma falha informada;
o programa não escolhe uma porta arbitrária. Se o relé estiver desconectado,
o pulso falha; após reconectá-lo, a próxima solicitação detecta a nova porta.
Cada pulso abre a porta, envia ligar, aguarda cinco segundos e envia desligar
em `finally`. Ao fechar o programa, o pulso é interrompido, tenta-se desligar
e pulsos pendentes são descartados. Falhas são exibidas na GUI e no terminal;
não há repetição automática de um acionamento que falhou.

Não use o controle manual simultaneamente ao acionamento pelo AutoWeight.

Para uma sirene que deve soar quando o relé é acionado, use os contatos
**COM e NO** conforme a identificação da placa. Esses contatos comutam a
alimentação externa da sirene; o USB alimenta o módulo. Confira a tensão e
a corrente da sirene e a capacidade dos contatos antes da ligação.
