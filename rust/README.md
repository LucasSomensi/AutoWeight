# AutoWeight Rust — versão oficial

CLI e GUI compartilham o motor de aquisição e pesagem. O Python em
`../legacy/python/` é legado congelado e não é usado pelos executáveis oficiais.

```powershell
cd C:\Users\Lucas\AutoWeight\rust
cargo test --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo run --locked --bin autoweight
cargo run --locked --bin autoweight-cli -- --verbose
```

Execute `../compilar_rust.ps1` para gerar os dois executáveis de release em
`../bin` e `../criar_atalho.ps1` para apontar `AutoWeight.lnk` para a GUI Rust.

## Organização

- `domain.rs`: parser serial, estabilidade, substituição e regras da API.
- `runtime.rs`: leitura serial, reconexão, estado compartilhado e encerramento.
- `camera.rs`: FFmpeg RTSP/TCP, JPEG por pipe, watchdog e reconexão.
- `photos.rs`: gravação atômica, contingência incorporada e histórico compatível.
- `api.rs`: pendente mais recente, HTTPS/Bearer, timeout, backoff e logs rotativos.
- `relay.rs`: identificação CH340, protocolo LCUS-1 e pulsos em segundo plano.
- `config.rs`: `.env` literal, prioridade do ambiente e localização do FFmpeg.
- `gui.rs`: painel egui, histórico, ampliação, modo ausente, prévia ao vivo
  após 2 segundos de hover na câmera e botão de teste da sirene (5 segundos).
- `lib.rs`: argumentos, CLI, Ctrl+C e comandos manuais do relé.

## Validação

Os testes cobrem estabilidade, limites, troca do modo ausente, retentativas,
reconexão, substituição, API zero/negativos, deduplicação, classificação HTTP,
parser serial e JPEG fragmentados, contingência, histórico, configuração e relé.

Para testar abertura e encerramento da GUI sem acessar hardware ou rede:

```powershell
cargo run --locked --bin autoweight -- --demo --smoke-test
```

Os testes não enviam dados à API de produção nem acionam a sirene física.
Para incluir o teste de vídeo sintético com o FFmpeg instalado, execute
`cargo test --locked -- --include-ignored`. A integração HTTP é validada contra
um servidor local, verificando o payload, Bearer, retentativa, substituição do
pendente e ausência de credenciais no log.
O encerramento aguarda as tarefas: serial com timeout de 100 ms, câmera
interrompida pelo término do subprocesso, sirene com tentativa de OFF e HTTP
limitado a 20 segundos no total (conexão 5 s, leitura 15 s).

Ambiente: Rust estável x64 MSVC, Build Tools C++/Windows SDK e FFmpeg.
Versões das crates fixadas em `Cargo.lock`. O Smart App Control foi desativado
pelo usuário nesta máquina após bloquear os build scripts do Cargo.

Veja [instruções de operação e configuração](../readme.md).
