use crate::runtime::{Shared, Stop, wait};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::Path,
    sync::{Arc, Mutex},
    thread::{self, JoinHandle},
    time::Duration,
};
pub type Pending = Arc<Mutex<Option<i64>>>;

#[derive(Default)]
pub struct Delivery {
    pub pending: Option<i64>,
    pub last: Option<i64>,
    pub blocked: bool,
    pub delay: u64,
}
impl Delivery {
    pub fn next(&mut self) -> Option<i64> {
        if self.blocked {
            return None;
        }
        if self.pending == self.last {
            self.pending = None;
        }
        self.pending
    }
    pub fn result(&mut self, weight: i64, status: Option<u16>) -> bool {
        if status.is_some_and(|s| (200..300).contains(&s)) {
            self.last = Some(weight);
            if self.pending == Some(weight) {
                self.pending = None;
            }
            self.delay = 1;
            true
        } else {
            self.last = None;
            self.blocked = status.is_some_and(|s| ![500, 502, 503, 504].contains(&s));
            false
        }
    }
}
pub fn spawn(
    url: String,
    key: String,
    data: std::path::PathBuf,
    stop: Stop,
    state: Shared,
) -> (Pending, JoinHandle<()>) {
    let pending: Pending = Arc::new(Mutex::new(None));
    let input = pending.clone();
    let worker = thread::spawn(move || {
        if OpenOptions::new()
            .create(true)
            .append(true)
            .open(data.join("agrolima.log"))
            .is_err()
        {
            state.lock().unwrap().api =
                "AgroLima: sem acesso ao log; envios desativados. Reinicie.".into();
            crate::runtime::say("AgroLima: sem acesso ao log; envios desativados.");
            return;
        }
        let client = reqwest::blocking::ClientBuilder::from(
            reqwest::Client::builder()
                .connect_timeout(Duration::from_secs(5))
                .read_timeout(Duration::from_secs(15))
                .timeout(Duration::from_secs(20))
                .redirect(reqwest::redirect::Policy::none()),
        )
        .build();
        let Ok(client) = client else {
            state.lock().unwrap().api = "AgroLima: falha ao inicializar cliente HTTPS.".into();
            return;
        };
        let mut delivery = Delivery {
            delay: 1,
            ..Default::default()
        };
        while !stop.stopped() {
            if let Some(w) = input.lock().unwrap().take() {
                delivery.pending = Some(w);
            }
            let Some(weight) = delivery.next() else {
                wait(&stop, Duration::from_millis(100));
                continue;
            };
            let status = client
                .post(&url)
                .bearer_auth(&key)
                .header("Accept", "application/json")
                .json(&serde_json::json!({"peso_kg":weight}))
                .send()
                .ok()
                .map(|r| r.status().as_u16());
            // Never log request URLs, headers, response bodies or error messages containing secrets.
            if let Err(_error) = log(&data, weight, status) {
                state.lock().unwrap().api =
                    "AgroLima: falha ao gravar log; envios interrompidos. Reinicie.".into();
                return;
            }
            if let Some(w) = input.lock().unwrap().take() {
                delivery.pending = Some(w);
            }
            if delivery.result(weight, status) {
                state.lock().unwrap().api = format!("AgroLima: {weight} kg enviado.");
            } else if delivery.blocked {
                state.lock().unwrap().api =
                    format!("AgroLima: HTTP {}. Corrija e reinicie.", status.unwrap());
            } else {
                state.lock().unwrap().api = format!(
                    "AgroLima: envio pendente (HTTP {}).",
                    status.map_or("rede/timeout".into(), |s| s.to_string())
                );
                wait(&stop, Duration::from_secs(delivery.delay));
                delivery.delay = (delivery.delay * 2).min(60);
            }
            crate::runtime::say(&state.lock().unwrap().api);
        }
    });
    (pending, worker)
}
fn log(data: &Path, weight: i64, status: Option<u16>) -> std::io::Result<()> {
    let path = data.join("agrolima.log");
    if fs::metadata(&path).is_ok_and(|m| m.len() >= 1_000_000) {
        let old = data.join("agrolima.log.3");
        if old.exists() {
            fs::remove_file(old)?;
        }
        for i in (1..=2).rev() {
            let src = data.join(format!("agrolima.log.{i}"));
            if src.exists() {
                fs::rename(src, data.join(format!("agrolima.log.{}", i + 1)))?;
            }
        }
        fs::rename(&path, data.join("agrolima.log.1"))?;
    }
    writeln!(
        OpenOptions::new().create(true).append(true).open(path)?,
        "{} Peso={weight} kg HTTP={} resultado={}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S"),
        status.map_or("rede/timeout".into(), |s| s.to_string()),
        if status.is_some_and(|s| (200..300).contains(&s)) {
            "enviado"
        } else {
            "falha"
        }
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_http_payload_retry_latest_and_redaction() {
        use std::{io::Read, net::TcpListener, time::Instant};
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        listener.set_nonblocking(true).unwrap();
        let data = std::env::temp_dir().join(format!(
            "autoweight-api-test-{}-{}",
            std::process::id(),
            chrono::Local::now().timestamp_nanos_opt().unwrap()
        ));
        fs::create_dir_all(&data).unwrap();
        let stop = Stop::default();
        let state = Arc::new(Mutex::new(crate::runtime::State::default()));
        let (pending, worker) = spawn(
            format!("http://{addr}/api/balancas/1/peso"),
            "test-secret".into(),
            data.clone(),
            stop.clone(),
            state.clone(),
        );
        *pending.lock().unwrap() = Some(500);
        for (expected, status) in [(500, "503 Service Unavailable"), (700, "200 OK")] {
            let deadline = Instant::now() + Duration::from_secs(10);
            let mut stream = loop {
                match listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        assert!(Instant::now() < deadline);
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(e) => panic!("{e}"),
                }
            };
            // Accepted sockets can inherit the listener's nonblocking mode on Windows.
            stream.set_nonblocking(false).unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            let mut buf = [0; 2048];
            loop {
                let n = stream.read(&mut buf).unwrap();
                assert!(n > 0);
                request.extend_from_slice(&buf[..n]);
                if let Some(end) = request.windows(4).position(|b| b == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..end]).to_ascii_lowercase();
                    let length: usize = headers
                        .lines()
                        .find_map(|line| line.strip_prefix("content-length: "))
                        .unwrap()
                        .parse()
                        .unwrap();
                    if request.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            let request = String::from_utf8(request).unwrap();
            assert!(request.starts_with("POST /api/balancas/1/peso HTTP/1.1"));
            assert!(
                request
                    .to_ascii_lowercase()
                    .contains("authorization: bearer test-secret")
            );
            let body = request.split_once("\r\n\r\n").unwrap().1;
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(body).unwrap()["peso_kg"],
                expected
            );
            if expected == 500 {
                *pending.lock().unwrap() = Some(700);
            }
            write!(
                stream,
                "HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            .unwrap();
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        while !state.lock().unwrap().api.contains("700 kg enviado") {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        stop.stop();
        worker.join().unwrap();
        let logs = fs::read_to_string(data.join("agrolima.log")).unwrap();
        assert!(logs.contains("HTTP=503"));
        assert!(logs.contains("HTTP=200"));
        assert!(!logs.contains("test-secret"));
        fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn newest_replaces_pending_and_dedup() {
        let mut d = Delivery {
            pending: Some(500),
            delay: 1,
            ..Default::default()
        };
        assert_eq!(d.next(), Some(500));
        d.pending = Some(700);
        assert!(!d.result(500, None));
        assert_eq!(d.next(), Some(700));
        assert!(d.result(700, Some(200)));
        d.pending = Some(700);
        assert_eq!(d.next(), None);
    }
    #[test]
    fn http_classification() {
        for s in [400, 401, 302, 413, 429] {
            let mut d = Delivery::default();
            d.result(500, Some(s));
            assert!(d.blocked);
        }
        for s in [500, 502, 503, 504] {
            let mut d = Delivery::default();
            d.result(500, Some(s));
            assert!(!d.blocked);
        }
    }
}
