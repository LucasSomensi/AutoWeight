use crate::{
    config::Config,
    runtime::{Shared, Stop, wait},
};
use std::{
    io::Read,
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
pub type Frame = Arc<Mutex<Option<(Instant, Vec<u8>)>>>;
// RTSP demuxer socket timeout (microseconds); rw_timeout is not accepted here.
const RTSP_OPTIONS: [&str; 4] = ["-rtsp_transport", "tcp", "-timeout", "5000000"];

pub fn spawn(config: &Config, stop: Stop, state: Shared) -> (Frame, JoinHandle<()>) {
    let frame: Frame = Arc::new(Mutex::new(None));
    let output = frame.clone();
    let config = config.clone();
    let worker = thread::spawn(move || {
        while !stop.stopped() {
            let mut command = Command::new(&config.ffmpeg);
            command
                .args(["-hide_banner", "-loglevel", "error"])
                .args(RTSP_OPTIONS)
                .args([
                    "-i",
                    &config.camera,
                    "-an",
                    "-vf",
                    "fps=5",
                    "-q:v",
                    "2",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ])
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let Ok(mut child) = command.spawn() else {
                state.lock().unwrap().message =
                    "FFmpeg indisponível. Verifique AUTOWEIGHT_FFMPEG.".into();
                wait(&stop, Duration::from_secs(3));
                continue;
            };
            let mut stdout = child.stdout.take().unwrap();
            let reader_frame = output.clone();
            let reader = thread::spawn(move || {
                let mut parser = Jpegs::default();
                let mut buf = [0u8; 16384];
                while let Ok(n) = stdout.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    for jpeg in parser.push(&buf[..n]) {
                        *reader_frame.lock().unwrap() = Some((Instant::now(), jpeg));
                    }
                }
            });
            let started = Instant::now();
            while !stop.stopped() {
                if !matches!(child.try_wait(), Ok(None)) {
                    break;
                }
                let last = output
                    .lock()
                    .unwrap()
                    .as_ref()
                    .map(|(t, _)| *t)
                    .unwrap_or(started);
                state.lock().unwrap().camera =
                    output.lock().unwrap().is_some() && last.elapsed() <= Duration::from_secs(2);
                if last.elapsed() > Duration::from_secs(10) {
                    break;
                }
                wait(&stop, Duration::from_millis(100));
            }
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            *output.lock().unwrap() = None;
            state.lock().unwrap().camera = false;
            wait(&stop, Duration::from_secs(3));
        }
    });
    (frame, worker)
}

#[derive(Default)]
struct Jpegs {
    bytes: Vec<u8>,
}
impl Jpegs {
    fn push(&mut self, input: &[u8]) -> Vec<Vec<u8>> {
        self.bytes.extend_from_slice(input);
        let mut result = Vec::new();
        loop {
            let Some(start) = self.bytes.windows(2).position(|w| w == [0xff, 0xd8]) else {
                if self.bytes.len() > 1 {
                    self.bytes.drain(..self.bytes.len() - 1);
                }
                break;
            };
            if start > 0 {
                self.bytes.drain(..start);
            }
            let Some(end) = self.bytes[2..]
                .windows(2)
                .position(|w| w == [0xff, 0xd9])
                .map(|p| p + 4)
            else {
                break;
            };
            let jpeg: Vec<_> = self.bytes.drain(..end).collect();
            if image::load_from_memory(&jpeg).is_ok() {
                result.push(jpeg);
            }
        }
        if self.bytes.len() > 32 * 1024 * 1024 {
            self.bytes.clear();
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[ignore = "Requer FFmpeg instalado; consulta opções sem acessar câmera"]
    fn rtsp_options_supported_by_ffmpeg() {
        let exe = crate::config::find_ffmpeg(std::path::Path::new("."));
        let mut command = Command::new(exe);
        command.args(["-hide_banner", "-h", "demuxer=rtsp"]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let output = command.output().unwrap();
        assert!(output.status.success());
        let help = String::from_utf8_lossy(&output.stdout);
        for option in RTSP_OPTIONS.iter().step_by(2) {
            assert!(
                help.lines()
                    .any(|line| line.split_whitespace().next() == Some(option)),
                "Opção RTSP não suportada: {option}"
            );
        }
    }
    #[test]
    #[ignore = "Requer FFmpeg instalado; usa vídeo sintético sem câmera"]
    fn ffmpeg_synthetic_video() {
        let exe = crate::config::find_ffmpeg(std::path::Path::new("."));
        let mut command = Command::new(exe);
        command.args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=5",
            "-frames:v",
            "2",
            "-q:v",
            "2",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let output = command.output().unwrap();
        assert!(output.status.success(), "FFmpeg falhou");
        let mut parser = Jpegs::default();
        let mut count = 0;
        for chunk in output.stdout.chunks(17) {
            count += parser.push(chunk).len();
        }
        assert_eq!(count, 2);
    }
    #[test]
    fn fragmented_jpeg_pipe() {
        let bytes = crate::photos::fallback().unwrap();
        let mut parser = Jpegs::default();
        assert!(parser.push(b"noise").is_empty());
        assert!(parser.push(&bytes[..100]).is_empty());
        assert_eq!(parser.push(&bytes[100..]), vec![bytes.clone()]);
        let mut pair = bytes.clone();
        pair.extend(&bytes);
        assert_eq!(parser.push(&pair).len(), 2);
    }
}
