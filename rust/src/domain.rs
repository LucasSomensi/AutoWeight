//! Regras determinísticas, com relógio injetado para testes.
#[derive(Default, Debug)]
pub struct Stability {
    candidate: Option<i64>,
    start: f64,
    last: Option<f64>,
    maximum: i64,
    published: bool,
}

impl Stability {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn sample(&mut self, weight: i64, now: f64, seconds: f64, api: bool) -> Option<i64> {
        if api && !(0..=i32::MAX as i64).contains(&weight) {
            self.reset();
            return None;
        }
        if api && self.last.is_some_and(|last| now - last > 3.0) {
            self.reset();
        }
        self.last = Some(now);
        if self
            .candidate
            .is_none_or(|c| weight.abs_diff(c) > 20 || (api && (weight == 0) != (c == 0)))
        {
            self.candidate = Some(weight);
            self.start = now;
            self.maximum = weight;
            self.published = false;
            return None;
        }
        self.maximum = self.maximum.max(weight);
        if !self.published && now - self.start >= seconds {
            self.published = true;
            Some(self.maximum)
        } else {
            None
        }
    }
}

#[derive(Default)]
pub struct Weighing {
    stability: Stability,
    pub recorded: Option<i64>,
    pending: Option<i64>,
    attempted: Option<f64>,
}
impl Weighing {
    pub fn reconnect(&mut self) {
        self.stability.reset();
        self.pending = None;
    }
    pub fn sample(&mut self, weight: i64, now: f64, away: bool) -> Option<(i64, bool)> {
        if self.recorded.is_some() && weight < 300 {
            self.recorded = None;
            self.reconnect();
            return None;
        }
        if self.recorded.is_some_and(|r| weight <= r) || (self.recorded.is_none() && weight <= 1000)
        {
            self.reconnect();
            return None;
        }
        // Retain a failed attempt only while the candidate remains eligible and in range.
        let changed = self
            .stability
            .candidate
            .is_some_and(|c| weight.abs_diff(c) > 20);
        if changed {
            self.pending = None;
        }
        if let Some(max) = self
            .stability
            .sample(weight, now, if away { 5.0 } else { 3.0 }, false)
        {
            self.pending = Some(max);
        }
        if self.pending.is_some() {
            self.pending = Some(self.stability.maximum);
        }
        if self.attempted.is_some_and(|t| now - t < 3.0) {
            return None;
        }
        self.pending.map(|w| {
            self.attempted = Some(now);
            (w, self.recorded.is_some())
        })
    }
    pub fn saved(&mut self, weight: i64) {
        self.recorded = Some(weight);
        self.reconnect();
    }
}

pub fn parse_weight(line: &str) -> Option<(&str, i64)> {
    for (index, _) in line.char_indices() {
        let tail = &line[index..];
        if tail.starts_with("ST,GS,") || tail.starts_with("US,GS,") {
            let value = tail[6..].split_once("kg")?.0;
            if !value.starts_with(['+', '-'])
                || value.len() < 2
                || !value.as_bytes()[1..].iter().all(u8::is_ascii_digit)
            {
                continue;
            }
            return Some((&tail[..2], value.parse().ok()?));
        }
    }
    None
}

#[derive(Default)]
pub struct Lines {
    buffer: Vec<u8>,
}
impl Lines {
    pub fn push(&mut self, bytes: &[u8]) -> Vec<String> {
        let mut result = Vec::new();
        for &b in bytes {
            if b == b'\r' || b == b'\n' {
                if !self.buffer.is_empty() {
                    result.push(String::from_utf8_lossy(&self.buffer).trim().to_owned());
                    self.buffer.clear();
                }
            } else if self.buffer.len() < 4096 {
                self.buffer.push(b);
            } else {
                self.buffer.clear();
            }
        }
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn serial_fragmentation() {
        let mut lines = Lines::default();
        assert!(lines.push(b"ST,GS,+20").is_empty());
        assert_eq!(
            lines.push(b"00kg\r\nUS,GS,-2kg\n"),
            ["ST,GS,+2000kg", "US,GS,-2kg"]
        );
        assert_eq!(parse_weight("noiseST,GS,+2000kg"), Some(("ST", 2000)));
        for line in ["ST,GS,2kg", "ST,GS,+kg", "ST,GS,+2.0kg", "XX,GS,+2kg"] {
            assert!(parse_weight(line).is_none());
        }
    }
    #[test]
    fn replacement_and_reset() {
        let mut w = Weighing::default();
        assert_eq!(w.sample(1000, 0., false), None);
        w.sample(2000, 0., false);
        w.sample(2020, 2., false);
        assert_eq!(w.sample(2000, 3., false), Some((2020, false)));
        w.saved(2020);
        assert_eq!(w.sample(2000, 10., false), None);
        w.sample(2500, 11., false);
        assert_eq!(w.sample(2500, 14., false), Some((2500, true)));
        w.saved(2500);
        w.sample(299, 15., false);
        w.sample(3000, 16., false);
        assert_eq!(w.sample(3000, 19., false), Some((3000, false)));
    }
    #[test]
    fn away_changes_during_window_and_failed_save_retries() {
        let mut w = Weighing::default();
        w.sample(2000, 0., false);
        assert_eq!(w.sample(2000, 3., true), None);
        assert_eq!(w.sample(2000, 5., true), Some((2000, false)));
        assert_eq!(w.recorded, None);
        assert_eq!(w.sample(2000, 6., true), None);
        assert_eq!(w.sample(2010, 8., true), Some((2010, false)));
        w.sample(2500, 11., true);
        assert_eq!(w.sample(2500, 15., true), None);
        assert_eq!(w.sample(2500, 16., true), Some((2500, false)));
    }
    #[test]
    fn reconnect_clears_window_preserves_truck() {
        let mut w = Weighing::default();
        w.sample(2000, 0., false);
        w.reconnect();
        assert_eq!(w.sample(2000, 5., false), None);
        assert_eq!(w.sample(2000, 8., false), Some((2000, false)));
        w.saved(2000);
        w.reconnect();
        assert_eq!(w.sample(2000, 20., false), None);
    }
    #[test]
    fn api_zero_gap_negative_and_dedup() {
        let mut s = Stability::default();
        assert_eq!(s.sample(500, 0., 1., true), None);
        s.sample(520, 0.5, 1., true);
        assert_eq!(s.sample(500, 1., 1., true), Some(520));
        assert_eq!(s.sample(500, 2., 1., true), None);
        s.sample(-1, 3., 1., true);
        s.sample(20, 4., 1., true);
        assert_eq!(s.sample(0, 5., 1., true), None);
        assert_eq!(s.sample(0, 6., 1., true), Some(0));
        s.sample(100, 7., 1., true);
        assert_eq!(s.sample(100, 12., 1., true), None);
        assert_eq!(s.sample(100, 13., 1., true), Some(100));
        assert_eq!(s.sample(i32::MAX as i64 + 1, 14., 1., true), None);
    }
}
