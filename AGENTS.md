# AutoWeight

Rust em `rust/` é a implementação oficial da CLI e da GUI.
Os arquivos Python e seus testes em `legacy/python/` são legado congelado: mantenha-os
na codebase, sem atualizar, salvo instrução explícita do usuário.

Novas funcionalidades, correções e testes devem ser implementados em Rust.
Preserve a compatibilidade com `.env`, `AutoWeightData`, nomes das fotos e o
marcador JPEG de contingência existentes.

Validação a partir de `rust/`:

- `cargo test --locked` (com FFmpeg instalado, use `-- --include-ignored`).
- `cargo fmt --check`.
- `cargo clippy --locked --all-targets -- -D warnings`.

Use `--demo --smoke-test` para verificar a GUI sem equipamentos nem API.
`compilar_rust.ps1` gera os executáveis oficiais em `bin/` e
`criar_atalho.ps1` configura o atalho da GUI Rust.
