use anyhow::{Context, Result};
use chrono::{Local, NaiveDateTime};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
pub const MARKER: &[u8] = b"AutoWeight:contingencia:manga";
const FALLBACK: &[u8] = include_bytes!("../../assets/camera-indisponivel-manga.png");

#[derive(Clone, Debug)]
pub struct Record {
    pub path: PathBuf,
    pub time: NaiveDateTime,
    pub weight: i64,
}
pub fn list(data: &Path) -> Result<Vec<Record>> {
    if !data.exists() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    for entry in fs::read_dir(data)?.flatten() {
        let path = entry.path();
        if path.extension().is_none_or(|s| s != "jpg") {
            continue;
        }
        let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
            continue;
        };
        let Some((date, weight)) = stem.rsplit_once('-') else {
            continue;
        };
        let Some(weight) = weight.strip_suffix("kg").and_then(|s| s.parse().ok()) else {
            continue;
        };
        if let Ok(time) = NaiveDateTime::parse_from_str(date, "%Y-%m-%d-%H-%M-%S-%6f") {
            out.push(Record { path, time, weight });
        }
    }
    out.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(out)
}
pub fn fallback() -> Result<Vec<u8>> {
    let image = image::load_from_memory(FALLBACK)?.to_rgb8();
    let mut data = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut data, 95).encode_image(&image)?;
    let mut marked = vec![0xff, 0xd8, 0xff, 0xfe];
    marked.extend_from_slice(&((MARKER.len() + 2) as u16).to_be_bytes());
    marked.extend_from_slice(MARKER);
    marked.extend_from_slice(&data[2..]);
    Ok(marked)
}
pub fn save(data: &Path, weight: i64, jpeg: Option<&[u8]>) -> Result<(Record, bool)> {
    fs::create_dir_all(data)?;
    let now = Local::now().naive_local();
    let path = data.join(format!(
        "{}-{weight}kg.jpg",
        now.format("%Y-%m-%d-%H-%M-%S-%6f")
    ));
    if let Some(jpeg) = jpeg
        && image::load_from_memory(jpeg).is_ok()
        && atomic_write(&path, jpeg).is_ok()
    {
        return Ok((
            Record {
                path,
                time: now,
                weight,
            },
            false,
        ));
    }
    atomic_write(&path, &fallback()?).context("Falha ao gravar a imagem de contingência")?;
    Ok((
        Record {
            path,
            time: now,
            weight,
        },
        true,
    ))
}
pub fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    let temp = path.with_extension("jpg.tmp");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temp)?;
    let result = (|| -> Result<()> {
        file.write_all(data)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}
pub fn contingency(bytes: &[u8]) -> bool {
    bytes
        .iter()
        .take(256)
        .copied()
        .collect::<Vec<_>>()
        .windows(MARKER.len())
        .any(|s| s == MARKER)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fallback_and_history_compatibility() {
        let dir = std::env::temp_dir().join(format!(
            "autoweight-test-{}-{}",
            std::process::id(),
            Local::now().timestamp_nanos_opt().unwrap()
        ));
        let (record, fallback) = save(&dir, 28500, None).unwrap();
        assert!(fallback);
        let bytes = fs::read(&record.path).unwrap();
        assert!(contingency(&bytes));
        assert!(image::load_from_memory(&bytes).is_ok());
        let records = list(&dir).unwrap();
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].weight, 28500);
        fs::write(dir.join("unrelated.jpg"), b"bad").unwrap();
        assert_eq!(list(&dir).unwrap().len(), 1);
        assert!(atomic_write(&dir.join("missing/path.jpg"), b"bad").is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
