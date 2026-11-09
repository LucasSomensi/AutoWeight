use crate::{
    api, camera,
    config::Config,
    domain::{Lines, Stability, Weighing},
    photos, relay,
};
use anyhow::Result;
use std::{
    io::ErrorKind,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

#[derive(Clone, Default)]
pub struct Stop(Arc<AtomicBool>);
impl Stop {
    pub fn stopped(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
    pub fn stop(&self) {
        self.0.store(true, Ordering::SeqCst);
    }
}
pub fn wait(stop: &Stop, duration: Duration) {
    let deadline = Instant::now() + duration;
    while !stop.stopped() && Instant::now() < deadline {
        thread::sleep(
            deadline
                .saturating_duration_since(Instant::now())
                .min(Duration::from_millis(50)),
        );
    }
}
pub fn say(message: &str) {
    println!(
        "[{}] {message}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S")
    );
}
#[derive(Clone)]
pub struct State {
    pub weight: Option<i64>,
    pub received: Option<Instant>,
    pub message: String,
    pub api: String,
    pub siren: String,
    pub away: bool,
    pub photo: Option<PathBuf>,
    pub camera: bool,
}
impl Default for State {
    fn default() -> Self {
        Self {
            weight: None,
            received: None,
            message: "Iniciando…".into(),
            api: String::new(),
            siren: "Sirene: aguardando registro.".into(),
            away: false,
            photo: None,
            camera: false,
        }
    }
}
pub type Shared = Arc<Mutex<State>>;
pub struct Runtime {
    pub state: Shared,
    pub stop: Stop,
    pub frame: camera::Frame,
    pub siren: relay::Siren,
    worker: Option<JoinHandle<()>>,
}
impl Runtime {
    pub fn start(config: Config, verbose: bool) -> Result<Self> {
        std::fs::create_dir_all(&config.data)?;
        let state = Arc::new(Mutex::new(State::default()));
        let stop = Stop::default();
        let s = state.clone();
        let end = stop.clone();
        let (frame, camera_worker) = camera::spawn(&config, stop.clone(), state.clone());
        let (siren, siren_worker) = relay::spawn(stop.clone(), state.clone());
        let services = Services {
            frame: frame.clone(),
            siren: siren.clone(),
            camera_worker,
            siren_worker,
        };
        let worker = thread::spawn(move || run(config, verbose, s, end, services));
        Ok(Self {
            state,
            stop,
            frame,
            siren,
            worker: Some(worker),
        })
    }
    pub fn toggle(&self) {
        let mut s = self.state.lock().unwrap();
        s.away = !s.away;
        say(if s.away {
            "Modo ausente ATIVADO."
        } else {
            "Modo ausente DESATIVADO."
        });
    }
    pub fn finished(&self) -> bool {
        self.worker.as_ref().is_none_or(JoinHandle::is_finished)
    }
    pub fn shutdown(&mut self) {
        self.stop.stop();
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
impl Drop for Runtime {
    fn drop(&mut self) {
        self.shutdown();
    }
}

struct Services {
    frame: camera::Frame,
    siren: relay::Siren,
    camera_worker: JoinHandle<()>,
    siren_worker: JoinHandle<()>,
}
fn run(config: Config, verbose: bool, state: Shared, stop: Stop, services: Services) {
    let Services {
        frame,
        siren,
        camera_worker,
        siren_worker,
    } = services;
    let api = config
        .api
        .clone()
        .map(|(url, key)| api::spawn(url, key, config.data.clone(), stop.clone(), state.clone()));
    state.lock().unwrap().api = if config.api_invalid {
        "AgroLima: configuração inválida. Corrija e reinicie."
    } else if api.is_some() {
        "AgroLima: aguardando peso estável."
    } else {
        "AgroLima: integração não configurada."
    }
    .into();
    say(&state.lock().unwrap().api);
    let mut weighing = Weighing::default();
    let mut stability = Stability::default();
    let epoch = Instant::now();
    let mut last_photo = None;
    let mut printed = None;
    let mut print_time = None;
    say("Lendo balança. Ctrl+C para encerrar. Pressione A para alternar modo ausente.");
    while !stop.stopped() {
        {
            let mut s = state.lock().unwrap();
            s.weight = None;
            s.message = format!("Conectando à balança ({})…", config.port);
        }
        let opened = serialport::new(&config.port, 9600)
            .data_bits(serialport::DataBits::Eight)
            .parity(serialport::Parity::None)
            .stop_bits(serialport::StopBits::One)
            .flow_control(serialport::FlowControl::None)
            .timeout(Duration::from_millis(100))
            .open();
        let mut port = match opened {
            Ok(p) => p,
            Err(_) => {
                state.lock().unwrap().message =
                    format!("Balança indisponível ({}). Reconectando…", config.port);
                say(&format!(
                    "Balança indisponível ({}). Nova tentativa em 5 segundos.",
                    config.port
                ));
                wait(&stop, Duration::from_secs(5));
                continue;
            }
        };
        let _ = port.clear(serialport::ClearBuffer::All);
        say("Balança conectada.");
        let mut lines = Lines::default();
        let mut last_data = Instant::now();
        let mut buf = [0u8; 2048];
        while !stop.stopped() {
            state.lock().unwrap().camera = frame
                .lock()
                .unwrap()
                .as_ref()
                .is_some_and(|(t, _)| t.elapsed() <= Duration::from_secs(2));
            match port.read(&mut buf) {
                Ok(n) if n > 0 => {
                    last_data = Instant::now();
                    for line in lines.push(&buf[..n]) {
                        let Some((status, weight)) = crate::domain::parse_weight(&line) else {
                            if verbose {
                                say("Linha serial inválida ignorada.");
                            }
                            continue;
                        };
                        let now = epoch.elapsed().as_secs_f64();
                        let away = {
                            let mut s = state.lock().unwrap();
                            s.weight = Some(weight);
                            s.received = Some(Instant::now());
                            s.message = "Recebendo peso da balança".into();
                            s.away
                        };
                        if verbose
                            || (printed != Some(weight)
                                && print_time.is_none_or(|t: f64| now - t >= 5.))
                        {
                            say(&format!("Peso: {weight} kg | status: {status}"));
                            printed = Some(weight);
                            print_time = Some(now);
                        }
                        if let Some((pending, _)) = &api
                            && let Some(w) = stability.sample(weight, now, 1., true)
                        {
                            *pending.lock().unwrap() = Some(w);
                        }
                        if let Some((max, replacement)) = weighing.sample(weight, now, away) {
                            let jpeg = frame
                                .lock()
                                .unwrap()
                                .as_ref()
                                .filter(|(t, _)| t.elapsed() <= Duration::from_secs(2))
                                .map(|(_, j)| j.clone());
                            match photos::save(&config.data, max, jpeg.as_deref()) {
                                Ok((record, fallback)) => {
                                    if replacement
                                        && let Some(path) = &last_photo
                                        && std::fs::remove_file(path).is_err()
                                    {
                                        say(
                                            "Foto nova salva, mas não foi possível remover a anterior.",
                                        );
                                    }
                                    last_photo = Some(record.path.clone());
                                    weighing.saved(max);
                                    {
                                        let mut s = state.lock().unwrap();
                                        s.photo = Some(record.path);
                                        s.message = if fallback {
                                            "Pesagem registrada com imagem de contingência."
                                        } else {
                                            "Pesagem registrada."
                                        }
                                        .into();
                                    }
                                    say(&format!(
                                        "Pesagem registrada: {max} kg{}",
                                        if fallback { " (contingência)" } else { "" }
                                    ));
                                    if !replacement && state.lock().unwrap().away {
                                        siren.trigger();
                                    }
                                }
                                Err(_) => {
                                    state.lock().unwrap().message =
                                        "Falha ao salvar pesagem. Nova tentativa em 3 segundos."
                                            .into();
                                    say("Falha ao salvar pesagem; registro ainda pendente.");
                                }
                            }
                        }
                    }
                }
                Err(e) if e.kind() != ErrorKind::TimedOut && e.kind() != ErrorKind::WouldBlock => {
                    break;
                }
                _ => {}
            }
            if last_data.elapsed() > Duration::from_secs(15) {
                say("Sem dados há 15 segundos. Reabrindo porta.");
                break;
            }
        }
        drop(port);
        weighing.reconnect();
        stability.reset();
        {
            let mut s = state.lock().unwrap();
            s.weight = None;
            s.received = None;
            s.message = "Reconectando à balança…".into();
        }
        wait(&stop, Duration::from_secs(2));
    }
    let _ = siren_worker.join();
    let _ = camera_worker.join();
    if let Some((_, worker)) = api {
        let _ = worker.join();
    }
    state.lock().unwrap().message = "Conexões encerradas.".into();
}
