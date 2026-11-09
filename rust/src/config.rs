use anyhow::{Context, Result, bail};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};

#[derive(Clone)]
pub struct Config {
    pub data: PathBuf,
    pub port: String,
    pub camera: String,
    pub ffmpeg: PathBuf,
    pub api: Option<(String, String)>,
    pub api_invalid: bool,
}

pub fn api_config(base: &str, key: &str) -> Result<Option<(String, String)>> {
    let base = base.trim().trim_end_matches('/');
    if base.is_empty() && key.is_empty() {
        return Ok(None);
    }
    let base = if base.contains("://") {
        base.to_owned()
    } else {
        format!("https://{base}")
    };
    let url = reqwest::Url::parse(&base).context("Origem AgroLima inválida")?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
        || key.is_empty()
        || key.chars().any(char::is_whitespace)
    {
        bail!("Configure a origem HTTPS do AgroLima e uma chave sem espaços");
    }
    Ok(Some((
        format!("{base}/api/balancas/1/peso"),
        key.to_owned(),
    )))
}

impl Config {
    pub fn load(root: PathBuf, port: Option<String>) -> Result<Self> {
        let root = root
            .canonicalize()
            .context("Diretório do aplicativo não encontrado")?;
        let env_path = root.join(".env");
        let values: HashMap<String, String> = if env_path.exists() {
            // Remove UTF-8 BOM and disable interpolation: camera/password values are literal.
            let contents =
                std::fs::read_to_string(env_path).context("Não foi possível ler .env")?;
            parse_env(contents.trim_start_matches('\u{feff}'))?
        } else {
            HashMap::new()
        };
        let get = |name: &str| {
            std::env::var(name)
                .ok()
                .or_else(|| values.get(name).cloned())
                .unwrap_or_default()
        };
        let camera = get("AUTOWEIGHT_CAMERA_URL");
        let url = reqwest::Url::parse(&camera)
            .map_err(|_| anyhow::anyhow!("Configure AUTOWEIGHT_CAMERA_URL no .env (RTSP)"))?;
        if url.scheme() != "rtsp" || url.host_str().is_none() {
            bail!("A câmera precisa de uma URL RTSP válida");
        }
        let api = api_config(&get("AGROLIMA_BASE_URL"), &get("AGROLIMA_API_KEY"));
        let api_invalid = api.is_err();
        let configured = get("AUTOWEIGHT_FFMPEG");
        let ffmpeg = if !configured.is_empty() {
            PathBuf::from(configured)
        } else {
            find_ffmpeg(&root)
        };
        Ok(Self {
            data: root.join("AutoWeightData"),
            port: port.unwrap_or_else(|| "COM5".into()),
            camera,
            ffmpeg,
            api: api.unwrap_or_default(),
            api_invalid,
        })
    }
}

fn parse_env(text: &str) -> Result<HashMap<String, String>> {
    // dotenv syntax with literal values: avoid dotenvy's environment interpolation.
    let mut values = HashMap::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let (name, value) = line.split_once('=').context("Linha inválida no .env")?;
        let value = value.trim();
        let value = if value.starts_with(['\'', '"']) {
            let quote = value.chars().next().unwrap();
            let end = value[1..]
                .find(quote)
                .context("Aspas não fechadas no .env")?
                + 1;
            value[1..end].to_owned()
        } else {
            value.split(" #").next().unwrap_or("").trim_end().to_owned()
        };
        values.insert(name.trim().to_owned(), value);
    }
    Ok(values)
}

pub(crate) fn find_ffmpeg(root: &Path) -> PathBuf {
    if root.join("ffmpeg.exe").is_file() {
        return root.join("ffmpeg.exe");
    }
    if let Some(path) = std::env::var_os("PATH") {
        for dir in std::env::split_paths(&path) {
            let exe = dir.join("ffmpeg.exe");
            if exe.is_file() {
                return exe;
            }
        }
    }
    // Also works when launched from Explorer before it refreshes the user PATH.
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let packages = PathBuf::from(local).join("Microsoft/WinGet/Packages");
        if let Ok(entries) = std::fs::read_dir(packages) {
            for p in entries
                .flatten()
                .filter(|p| p.file_name().to_string_lossy().starts_with("Gyan.FFmpeg_"))
            {
                if let Ok(versions) = std::fs::read_dir(p.path()) {
                    for v in versions.flatten() {
                        let exe = v.path().join("bin/ffmpeg.exe");
                        if exe.is_file() {
                            return exe;
                        }
                    }
                }
            }
        }
    }
    PathBuf::from("ffmpeg")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn origins() {
        assert_eq!(
            api_config("example.test/", "secret").unwrap().unwrap().0,
            "https://example.test/api/balancas/1/peso"
        );
        for base in [
            "http://example.test",
            "https://u:p@example.test",
            "https://example.test/path",
            "https://example.test?x=1",
            "https://example.test#x",
        ] {
            assert!(api_config(base, "key").is_err());
        }
        assert!(api_config("https://example.test", "a b").is_err());
        assert!(api_config("", "").unwrap().is_none());
    }
    #[test]
    fn literal_env() {
        let values =
            parse_env("PASSWORD=\"a${NOT_EXPANDED}#b\"\nexport URL='rtsp://u:p@host'\n# ignore")
                .unwrap();
        assert_eq!(values["PASSWORD"], "a${NOT_EXPANDED}#b");
        assert_eq!(values["URL"], "rtsp://u:p@host");
    }
}
