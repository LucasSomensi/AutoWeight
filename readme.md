# AutoWeight

**A versão oficial agora é Rust, tanto na CLI quanto na GUI.** Os arquivos
Python e seus testes permanecem como legado congelado, sem novas atualizações.
As instruções antigas estão preservadas na seção histórica abaixo.

## Executar a versão oficial

Abra `AutoWeight.lnk` ou `Iniciar-AutoWeight.cmd` para usar a GUI sem console.
No terminal:

```powershell
.\AutoWeight-CLI.cmd
.\AutoWeight-CLI.cmd --verbose
.\AutoWeight-CLI.cmd --porta COM5
```

**A** alterna o modo ausente sem Enter; **Ctrl+C** encerra. Na GUI, use o botão
Modo ausente e feche a janela para encerrar as conexões. O painel inclui peso,
estado da câmera, fotos com navegação/ampliação e estados da API e da sirene.

Mantenha o mouse sobre **Câmera conectada** por 2 segundos para ver uma prévia
ao vivo. A prévia usa a captura existente e desaparece ao retirar o mouse.
O botão **Testar sirene** solicita um pulso de 5 segundos, mesmo com o modo
ausente desativado; fica indisponível enquanto há acionamento pendente.

O `.env` e `AutoWeightData` continuam na raiz. O programa localiza a configuração
a partir do executável; `--diretorio PASTA` seleciona outra instalação. Variáveis
de ambiente têm prioridade. Não execute Rust e Python simultaneamente.

## Compilar e configurar o atalho

Requisitos: Rust estável x64 MSVC, Build Tools C++/Windows SDK e FFmpeg,
já instalados nesta máquina.

```powershell
powershell -ExecutionPolicy Bypass -File .\compilar_rust.ps1
powershell -ExecutionPolicy Bypass -File .\criar_atalho.ps1
```

Os executáveis oficiais ficam em `bin/`: `autoweight.exe` (GUI) e
`autoweight-cli.exe` (terminal). `autoweight.exe --sem-gui` também aceita o modo
terminal. FFmpeg é localizado no PATH, junto ao aplicativo ou na instalação
WinGet. `AUTOWEIGHT_FFMPEG=C:\caminho\ffmpeg.exe` no `.env` permite indicar outro.
O ícone e a ilustração de contingência estão incorporados no executável.

Para distribuir, mantenha `bin/`, os scripts de inicialização, `.env` e
`AutoWeightData` na mesma estrutura; instale FFmpeg e o runtime MSVC no destino.
Não distribua credenciais de produção junto ao aplicativo.

## Regras da versão Rust

- COM5, 9600 baud, 8N1, sem controle de fluxo; `--porta` altera a porta.
- Peso acima de 1.000 kg, por 3 segundos dentro de ±20 kg do candidato;
  5 segundos no modo ausente. O registro usa o maior peso da janela.
- Peso maior estabilizado substitui a foto do mesmo caminhão após salvar a nova.
  Peso abaixo de 300 kg libera o próximo caminhão.
- Câmera RTSP/TCP em segundo plano, foto com até 2 segundos. Sem imagem recente,
  salva a ilustração de contingência com marcador JPEG compatível com o legado.
  Falhas de gravação recebem novas tentativas a cada 3 segundos.
- Peso expira após 3 segundos sem leitura válida. Após 15 segundos sem dados,
  a serial reconecta e a avaliação de estabilidade recomeça.
- API AgroLima independente das fotos: estabilidade de 1 segundo; inteiros de
  0 a 2147483647; HTTPS/Bearer; sem redirecionamentos. Rede e HTTP 500/502/503/504
  recebem backoff de 1 até 60 segundos, mantendo o pendente mais recente.
  Outros erros HTTP suspendem os envios até reiniciar. Logs sem credenciais em
  `AutoWeightData/agrolima.log`, com rotação em 1 MB e três cópias.
- No modo ausente, apenas o primeiro registro salvo do caminhão aciona a sirene
  por 5 segundos. O relé é identificado por VID/PID 1A86:7523 antes de cada pulso.
  Ao encerrar, tenta desligar o relé. Pendências da API não persistem ao fechar.
- Fotos antigas continuam no histórico, incluindo identificação de contingência.

Comandos manuais do relé em Rust:

```powershell
.\AutoWeight-CLI.cmd rele listar
.\AutoWeight-CLI.cmd rele teste
.\AutoWeight-CLI.cmd rele pulso --segundos 2
```

## Desenvolvimento Rust

```powershell
cd rust
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked --bin autoweight -- --demo
```

`--demo` abre o painel sem hardware nem rede. `--demo --smoke-test` fecha o
painel após 3 segundos para verificar inicialização/encerramento. Os testes não
acionam o relé físico nem enviam dados à API de produção. A validação física
deve ser feita no ambiente de operação. Veja [rust/README.md](rust/README.md).

---

## Legado Python

Os scripts, testes e dependências Python estão em [legacy/python/](legacy/python/README.md),
preservados sem manutenção. A documentação histórica foi movida para essa pasta.
