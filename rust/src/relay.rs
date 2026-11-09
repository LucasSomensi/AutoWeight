use crate::runtime::{Shared, Stop, wait};
use anyhow::{Result, bail};
use serialport::{SerialPort, SerialPortType};
use std::{
    sync::mpsc::{self, Sender},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    thread::{self, JoinHandle},
    time::Duration,
};

pub fn locate(manual: Option<&str>) -> Result<String> {
    let ports: Vec<_> = serialport::available_ports()?
        .into_iter()
        .filter(|p| {
            matches!(&p.port_type,SerialPortType::UsbPort(u) if u.vid==0x1a86 && u.pid==0x7523)
                && manual.is_none_or(|name| name.eq_ignore_ascii_case(&p.port_name))
        })
        .collect();
    if ports.len() != 1 {
        bail!(
            "Esperado um único relé CH340 (1A86:7523); encontrados {}",
            ports.len()
        );
    }
    Ok(ports[0].port_name.clone())
}
pub fn packet(enabled: bool) -> [u8; 4] {
    [0xa0, 1, u8::from(enabled), 0xa1 + u8::from(enabled)]
}
pub fn send(port: &mut dyn SerialPort, enabled: bool) -> Result<()> {
    port.write_all(&packet(enabled))?;
    port.flush()?;
    Ok(())
}
pub fn pulse(name: &str, seconds: f64, stop: &Stop) -> Result<()> {
    let mut port = serialport::new(name, 9600)
        .timeout(Duration::from_secs(2))
        .flow_control(serialport::FlowControl::None)
        .open()?;
    // An OFF command is attempted even if enabling or waiting fails.
    let result = send(&mut *port, true);
    if result.is_ok() {
        wait(stop, Duration::from_secs_f64(seconds));
    }
    let off = send(&mut *port, false);
    result.and(off)
}
#[derive(Clone)]
pub struct Siren {
    sender: Sender<()>,
    pending: Arc<AtomicUsize>,
}
impl Siren {
    pub fn busy(&self) -> bool {
        self.pending.load(Ordering::SeqCst) > 0
    }
    pub fn trigger(&self) {
        self.pending.fetch_add(1, Ordering::SeqCst);
        if self.sender.send(()).is_err() {
            self.pending.fetch_sub(1, Ordering::SeqCst);
        }
    }
    pub fn test(&self) -> bool {
        if self
            .pending
            .compare_exchange(0, 1, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return false;
        }
        if self.sender.send(()).is_err() {
            self.pending.fetch_sub(1, Ordering::SeqCst);
            return false;
        }
        true
    }
}
pub fn spawn(stop: Stop, state: Shared) -> (Siren, JoinHandle<()>) {
    let (sender, receiver) = mpsc::channel();
    let pending = Arc::new(AtomicUsize::new(0));
    let active = pending.clone();
    let worker = thread::spawn(move || {
        while !stop.stopped() {
            if receiver.recv_timeout(Duration::from_millis(100)).is_err() {
                continue;
            }
            if stop.stopped() {
                break;
            }
            let result = (|| -> Result<()> {
                let name = locate(None)?;
                state.lock().unwrap().siren = format!("Sirene: acionada por 5 segundos ({name}).");
                pulse(&name, 5., &stop)
            })();
            let message = match result {
                Ok(()) => "Sirene: desligada.".into(),
                Err(e) => format!("Sirene: falha no relé ({e})."),
            };
            crate::runtime::say(&message);
            state.lock().unwrap().siren = message;
            active.fetch_sub(1, Ordering::SeqCst);
        }
    });
    (Siren { sender, pending }, worker)
}
#[cfg(test)]
mod tests {
    #[test]
    fn manual_test_does_not_queue_duplicates_or_drop_automatic_requests() {
        use super::*;
        let (sender, receiver) = mpsc::channel();
        let siren = Siren {
            sender,
            pending: Arc::new(AtomicUsize::new(0)),
        };
        assert!(siren.test());
        assert!(siren.busy());
        assert!(!siren.test());
        siren.trigger();
        assert_eq!(siren.pending.load(Ordering::SeqCst), 2);
        receiver.try_recv().unwrap();
        siren.pending.fetch_sub(1, Ordering::SeqCst);
        assert!(!siren.test());
        receiver.try_recv().unwrap();
        siren.pending.fetch_sub(1, Ordering::SeqCst);
        assert!(!siren.busy());
        assert!(siren.test());
        drop(receiver);
        siren.pending.store(0, Ordering::SeqCst);
        assert!(!siren.test());
        assert!(!siren.busy());
    }
    #[test]
    fn protocol() {
        assert_eq!(super::packet(true), [0xa0, 1, 1, 0xa2]);
        assert_eq!(super::packet(false), [0xa0, 1, 0, 0xa1]);
    }
}
