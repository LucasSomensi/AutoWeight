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

Para abrir com o terminal disponível para diagnóstico, use `python main.py`.

A interface mostra o peso atual, o indicador de conexão da câmera
e a última foto registrada, com data, hora e peso. A última foto salva também
é recuperada ao abrir o programa. Imagens brancas de contingência são sinalizadas.
O peso fica indisponível após 3 segundos sem uma leitura válida; a câmera é
considerada conectada quando há uma imagem recebida nos últimos 2 segundos.
Feche a janela para encerrar as conexões.

Para executar apenas no terminal, use `python main.py --sem-gui` e encerre
com `Ctrl+C`. A opção `--verbose` mostra todos os pesos no terminal em ambos
os modos. A interface usa Tkinter, incluído na instalação padrão do Python
para Windows, sem dependências adicionais.

## Configuração

A balança usa **COM5, 9600 baud, 8N1**, sem controle de fluxo.
Para alterar a porta ou os limites de pesagem, edite as constantes no início
de `main.py`. A placa utiliza o driver MaxLinear/Exar 5.5.0.0 x64.

A câmera já está configurada neste computador em `camera.local.json`.
Esse arquivo contém a URL com as credenciais e não é incluído no Git.
Em outro computador, crie o arquivo ao lado de `main.py` neste formato:

```json
{"rtsp_url": "rtsp://USUARIO:SENHA@IP:554/cam/realmonitor?channel=1&subtype=0"}
```

A variável de ambiente `AUTOWEIGHT_CAMERA_URL`, se definida, tem prioridade.
A câmera é lida continuamente em segundo plano e reconecta automaticamente.
Os limites de espera de conexão e leitura usam o backend FFmpeg do
[OpenCV](https://docs.opencv.org/4.10.0/d4/d15/group__videoio__flags__base.html).

## Fotos das pesagens

Exemplo de nome: `2026-09-07-14-30-05-123456-28500kg.jpg`.
O nome contém a data e hora local do computador, incluindo microssegundos
para evitar colisões, e o peso em kg.

- O peso precisa superar 1000 kg e permanecer por 5 segundos dentro de
  ±20 kg do peso candidato. O nome usa o maior peso dessa janela.
- A foto é a imagem recente disponível no momento do registro (até 2 segundos
  desde o recebimento); não necessariamente corresponde ao instante do peso máximo.
- Um peso maior que estabilize antes de o caminhão sair substitui a foto
  anterior, somente depois que a nova foto for salva com sucesso.
- A queda abaixo de 300 kg libera a próxima pesagem.
- Sem imagem recente, ou se a captura ou gravação da foto falhar, o programa
  salva uma imagem totalmente branca de 1920 × 1080, com o mesmo nome contendo
  data, hora e peso, e considera a pesagem registrada normalmente.
- Se nem a imagem branca puder ser gravada (por exemplo, disco cheio), o
  programa avisa e tenta novamente a cada 3 segundos enquanto o peso continuar
  elegível e estável. A foto anterior só é removida após salvar a nova imagem.

`AutoWeightData` não é incluída no Git. Preserve essa pasta: as fotos são os
registros de pesagem. `teste-camera.jpg` é apenas a imagem de verificação da
câmera, sem peso associado.

Após 15 segundos sem dados da balança, o programa reabre a porta e reinicia
a avaliação de estabilidade.

## Verificação

```powershell
python -B -m unittest discover -s tests
```
