mod api;
mod camera;
mod config;
mod domain;
mod gui;
mod photos;
mod relay;
mod runtime;
use anyhow::{Context, Result, bail};
use std::{path::PathBuf, time::Duration};

#[derive(Default)]
struct Options {
    cli: bool,
    verbose: bool,
    root: Option<PathBuf>,
    port: Option<String>,
    demo: bool,
    smoke: bool,
    relay: Option<String>,
    seconds: f64,
}
fn options(default_cli: bool) -> Result<Option<Options>> {
    let mut options = Options {
        cli: default_cli,
        seconds: 1.,
        ..Default::default()
    };
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--help" | "-h" => {
                println!(
                    "AutoWeight — aplicativo oficial em Rust\n\nUso: autoweight [--sem-gui] [--verbose] [--diretorio PASTA] [--porta COM5]\n     autoweight-cli [opções]\n     autoweight-cli rele listar|ligar|desligar|pulso|teste [--porta COM7] [--segundos 2]\n\nA: alternar modo ausente no terminal. Ctrl+C: encerrar.\n--demo: painel sem hardware/rede; --smoke-test: fechar demo após 3 segundos.\n--diretorio: pasta com .env e AutoWeightData (independente do diretório do terminal)."
                );
                return Ok(None);
            }
            "--version" | "-V" => {
                println!("AutoWeight {} (Rust)", env!("CARGO_PKG_VERSION"));
                return Ok(None);
            }
            "--sem-gui" => options.cli = true,
            "--verbose" | "-verbose" => options.verbose = true,
            "--diretorio" => {
                options.root = Some(PathBuf::from(args.next().context("Informe --diretorio")?))
            }
            "--porta" => options.port = Some(args.next().context("Informe --porta")?),
            "--segundos" => {
                options.seconds = args
                    .next()
                    .context("Informe --segundos")?
                    .parse()
                    .context("Duração inválida")?
            }
            "--demo" => options.demo = true,
            "--smoke-test" => options.smoke = true,
            "rele" => {
                options.relay = Some(args.next().context("Informe a ação do relé")?);
                options.cli = true;
            }
            _ => bail!("Argumento desconhecido: {arg}. Use --help."),
        }
    }
    if options.smoke && !options.demo {
        bail!("--smoke-test exige --demo para não acessar hardware");
    }
    Ok(Some(options))
}
fn root() -> Result<PathBuf> {
    let executable = std::env::current_exe()?;
    for ancestor in executable.ancestors().skip(1) {
        if ancestor.join("assets").is_dir() || ancestor.join(".env").is_file() {
            return Ok(ancestor.to_owned());
        }
    }
    // Distributed binaries live beside .env and AutoWeightData.
    Ok(executable
        .parent()
        .context("Executável sem diretório")?
        .to_owned())
}

pub fn entry(default_cli: bool) -> Result<()> {
    let Some(options) = options(default_cli)? else {
        return Ok(());
    };
    if let Some(action) = &options.relay {
        return manual_relay(action, &options);
    }
    let root = options.root.clone().map_or_else(root, Ok)?;
    let config = config::Config::load(root.clone(), options.port.clone());
    if !options.cli {
        return gui::run(root, config, options.verbose, options.demo, options.smoke);
    }
    if options.demo {
        bail!("--demo está disponível na interface gráfica; use autoweight --demo");
    }
    let mut runtime = runtime::Runtime::start(config?, options.verbose)?;
    let stop = runtime.stop.clone();
    ctrlc::set_handler(move || stop.stop()).context("Não foi possível configurar Ctrl+C")?;
    while !runtime.stop.stopped() && !runtime.finished() {
        if key() == Some('a') {
            runtime.toggle();
        }
        runtime::wait(&runtime.stop, Duration::from_millis(50));
    }
    runtime.shutdown();
    Ok(())
}
fn key() -> Option<char> {
    #[cfg(windows)]
    {
        #[link(name = "msvcrt")]
        unsafe extern "C" {
            fn _kbhit() -> i32;
            fn _getwch() -> u16;
        }
        // CRT reads only an available console key; extended keys are consumed together.
        unsafe {
            if _kbhit() != 0 {
                let k = _getwch();
                if k == 0 || k == 0xe0 {
                    _getwch();
                } else {
                    return char::from_u32(k as u32).map(|c| c.to_ascii_lowercase());
                }
            }
        }
    }
    None
}
fn manual_relay(action: &str, options: &Options) -> Result<()> {
    if action == "listar" {
        for port in serialport::available_ports()? {
            println!("{} {:?}", port.port_name, port.port_type);
        }
        return Ok(());
    }
    if !["ligar", "desligar", "pulso", "teste"].contains(&action) {
        bail!("Ação de relé inválida");
    }
    if !options.seconds.is_finite() || options.seconds <= 0. || options.seconds > 60. {
        bail!("--segundos deve ser maior que 0 e até 60");
    }
    let name = relay::locate(options.port.as_deref())?;
    if action == "ligar" || action == "desligar" {
        let mut port = serialport::new(name, 9600)
            .timeout(Duration::from_secs(2))
            .open()?;
        return relay::send(&mut *port, action == "ligar");
    }
    let stop = runtime::Stop::default();
    let end = stop.clone();
    ctrlc::set_handler(move || end.stop())?;
    for _ in 0..if action == "teste" { 3 } else { 1 } {
        if stop.stopped() {
            break;
        }
        relay::pulse(&name, options.seconds, &stop)?;
        runtime::wait(&stop, Duration::from_secs(1));
    }
    println!("Sequência concluída; relé desligado.");
    Ok(())
}
