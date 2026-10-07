# AutoWeight

Lê a balança pela serial e salva uma foto da câmera IP para cada pesagem
automática, na pasta `AutoWeightData` ao lado do programa. Não grava CSV.

## Uso

```powershell
python -m pip install -r requirements.txt
```

Para abrir **somente a GUI, sem o prompt de comando**, dê dois cliques em
`AutoWeight.pyw`. No Windows, arquivos `.pyw` usam o Python sem console
quando estão associados ao Python. Você também pode criar um atalho para esse
arquivo. Se a associação não estiver configurada, use `pythonw AutoWeight.pyw`.

O ícone da janela e da barra de tarefas é um robozinho. Para ter o mesmo ícone
ao abrir o aplicativo, execute `powershell -ExecutionPolicy Bypass -File .\criar_atalho.ps1`
uma vez e use o atalho `AutoWeight.lnk` criado na pasta. Você pode copiar esse
atalho para a área de trabalho. Recrie-o se mover a pasta ou reinstalar o Python.

Para abrir com o terminal disponível para diagnóstico, use `python main.py`.

A interface mostra o peso atual, o indicador de conexão da câmera
e a última foto registrada, com data, hora e peso. A última foto salva também
é recuperada ao abrir o programa. Imagens de contingência são sinalizadas,
inclusive ao consultar o histórico após reiniciar.
O peso fica indisponível após 3 segundos sem uma leitura válida; a câmera é
considerada conectada quando há uma imagem recebida nos últimos 2 segundos.
Feche a janela para encerrar as conexões.

Use os botões **◀** e **▶** para navegar pelas fotos salvas, da mais antiga
à mais recente. A data, a hora e o peso correspondem à foto exibida, e o
contador indica sua posição no histórico. Enquanto você consulta uma foto
antiga, novas pesagens não mudam sua seleção. Volte à foto mais recente para
acompanhar automaticamente os próximos registros. Fotos substituídas pelo
programa deixam de fazer parte do histórico.

Para executar apenas no terminal, use `python main.py --sem-gui` e encerre
com `Ctrl+C`. A opção `--verbose` mostra todos os pesos no terminal em ambos
os modos. A interface usa Tkinter, incluído na instalação padrão do Python
para Windows, sem dependências adicionais.

## Configuração

A balança usa **COM5, 9600 baud, 8N1**, sem controle de fluxo.
Para alterar a porta ou os limites de pesagem, edite as constantes no início
de `main.py`. A placa utiliza o driver MaxLinear/Exar 5.5.0.0 x64.

A câmera já está configurada neste computador em `.env`.
Esse arquivo contém a URL com as credenciais e não é incluído no Git.
Em outro computador, crie o arquivo ao lado de `main.py` neste formato:

```dotenv
AUTOWEIGHT_CAMERA_URL="rtsp://USUARIO:SENHA@IP:554/cam/realmonitor?channel=1&subtype=0"
```

A variável de ambiente `AUTOWEIGHT_CAMERA_URL`, se definida, tem prioridade.
A câmera é lida continuamente em segundo plano e reconecta automaticamente.
Os limites de espera de conexão e leitura usam o backend FFmpeg do
[OpenCV](https://docs.opencv.org/4.10.0/d4/d15/group__videoio__flags__base.html).

## Fotos das pesagens

Exemplo de nome: `2026-09-07-14-30-05-123456-28500kg.jpg`.
O nome contém a data e hora local do computador, incluindo microssegundos
para evitar colisões, e o peso em kg.

- O peso precisa superar 1000 kg e permanecer por 3 segundos dentro de
  ±20 kg do peso candidato. O nome usa o maior peso dessa janela.
- A foto é a imagem recente disponível no momento do registro (até 2 segundos
  desde o recebimento); não necessariamente corresponde ao instante do peso máximo.
- Um peso maior que estabilize antes de o caminhão sair substitui a foto
  anterior, somente depois que a nova foto for salva com sucesso.
- A queda abaixo de 300 kg libera a próxima pesagem.
- Sem imagem recente, ou se a captura ou gravação da foto falhar, o programa
  salva a ilustração em mangá de `assets/camera-indisponivel-manga.png`, com o mesmo nome contendo
  data, hora e peso, e considera a pesagem registrada normalmente.
- Se nem a imagem de contingência puder ser gravada (por exemplo, disco cheio
  ou arquivo da ilustração ausente), o
  programa avisa e tenta novamente a cada 3 segundos enquanto o peso continuar
  elegível e estável. A foto anterior só é removida após salvar a nova imagem.

`AutoWeightData` não é incluída no Git. Preserve essa pasta: as fotos são os
registros de pesagem. `teste-camera.jpg` é apenas a imagem de verificação da
câmera, sem peso associado.

Após 15 segundos sem dados da balança, o programa reabre a porta e reinicia
a avaliação de estabilidade.

## Integração com AgroLima

O programa publica os pesos estáveis **maiores ou iguais a zero** na balança 1,
conforme o [contrato da API](https://github.com/LucasSomensi/AgLima/blob/main/docs/api-balanca.md).
A avaliação é independente do registro de fotos: pesos abaixo de 1.000 kg e
quedas de peso também são enviados. Usa 1 segundo dentro de ±20 kg do candidato,
publicando o maior peso da janela. Uma mudança para zero inicia uma nova janela
para permitir a publicação de zero exato. Pesos negativos ou fora do limite da
API são descartados. Intervalos de mais de 3 segundos entre leituras reiniciam
a estabilidade. A mesma faixa gera apenas uma publicação até mudar de faixa.

Configure `.env` ao lado de `main.py` (já configurado neste computador):

```text
AGROLIMA_BASE_URL=https://SEU_DOMINIO.up.railway.app
AGROLIMA_API_KEY=SUA_CHAVE
```

Um domínio sem esquema recebe `https://` automaticamente. O domínio deve ser
a origem do site, sem caminho. `AGROLIMA_BASE_URL` e `AGROLIMA_API_KEY`, quando
definidas, têm prioridade sobre o arquivo. O arquivo é ignorado pelo Git;
restrinja o acesso a ele à conta que executa o programa. Reinicie o AutoWeight
após alterar a configuração. Sem configuração, o registro local continua ativo.

O envio ocorre em segundo plano, com timeout de conexão de 5 segundos e leitura
de 15 segundos. Falhas de rede e HTTP 500/502/503/504 recebem novas tentativas
com atrasos de 1, 2, 4, 8… até 60 segundos. O peso estável mais recente substitui
o pendente; não há fila histórica. Respostas HTTP não transitórias interrompem
os envios até corrigir o problema e reiniciar. Redirecionamentos não são seguidos.
Um peso igual ao último confirmado não é reenviado; após falha ambígua, pode
ser reenviado conforme permitido pelo contrato.

A barra inferior mostra o estado da integração. `AutoWeightData/agrolima.log`
registra horário, peso, resultado HTTP e categoria de erro, sem credenciais,
com rotação de arquivos. Pendências ficam em memória e não sobrevivem ao
encerramento; ao reabrir, o programa aguarda uma nova leitura estável.

## Relé USB para sirene

O relé conectado foi testado na **COM7** e os cliques foram confirmados.
Use `python -B relay_usb.py teste` para repetir os três pulsos ou
`python -B relay_usb.py pulso --segundos 2` para um pulso de dois segundos.
Veja [identificação, comandos e protocolo do relé](docs/rele-usb.md).
### Modo ausente

Use o botão **Modo ausente** na GUI para ativar ou desativar. No terminal
Windows (`python main.py --sem-gui`), pressione **A**, sem Enter, com o
terminal em foco. O programa inicia com o modo desativado; a seleção não
é salva ao encerrar.

Quando ativo, o primeiro registro salvo de cada caminhão aciona o relé da
sirene por **5 segundos**. Substituições por um peso maior não repetem o
acionamento. Um registro com imagem de contingência também conta como
pesagem salva; se a gravação falhar, a sirene só será acionada após um
registro bem-sucedido. Ativar o modo depois da primeira foto não aciona
a sirene retroativamente.

A sirene detecta automaticamente o único dispositivo USB **1A86:7523 (CH340)**
antes de cada pulso e funciona em segundo plano. Você pode trocar a entrada
USB ou reconectar o relé sem configurar a COM nem reiniciar o programa.
Se ele estiver desconectado, o pulso falha; após reconectar, a próxima
solicitação usa a porta atual. Pulsos que falharam não são repetidos.
Falhas aparecem no status da GUI e no terminal, sem interromper as pesagens.
Desativar o modo impede novos acionamentos; um pulso já solicitado termina
normalmente. Fechar o programa interrompe o pulso e tenta desligar o relé.
Evite usar o script manual enquanto o AutoWeight estiver acionando o relé.

## Testes

```powershell
python -B -m unittest discover -s tests
```
