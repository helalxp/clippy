use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    io::{self, BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeComponent {
    pub version: String,
    pub url: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub install_dir: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct DownloadProgress {
    pub component: String,
    pub downloaded: u64,
    pub total: u64,
    pub percent: f32,
}

pub struct Downloader {
    output_dir: PathBuf,
}

impl Downloader {
    pub fn new(output_dir: PathBuf) -> Self {
        Self { output_dir }
    }

    pub fn download(
        &self,
        component: &str,
        config: &RuntimeComponent,
        progress_callback: impl Fn(DownloadProgress),
    ) -> Result<PathBuf, String> {
        let filename = self
            .output_dir
            .join(format!("{}.zip", component));

        fs::create_dir_all(&self.output_dir)
            .map_err(|e| format!("Cannot create output directory: {e}"))?;

        let downloaded = if filename.exists() {
            fs::metadata(&filename).map(|m| m.len()).unwrap_or(0)
        } else {
            0
        };

        let client = ureq::AgentBuilder::new()
            .timeout(Duration::from_secs(30))
            .build();

        let mut request = client.get(&config.url);
        if downloaded > 0 && downloaded < config.size_bytes {
            request = request.set("Range", &format!("bytes={}-", downloaded));
        }

        let response = request.call().map_err(|e| format!("Download failed: {e}"))?;

        let status = response.status();
        if status != 200 && status != 206 {
            return Err(format!("HTTP error: {status}"));
        }

        let file = if downloaded > 0 && status == 206 {
            File::options().append(true).open(&filename)
        } else {
            File::create(&filename)
        };
        let mut file = file.map_err(|e| format!("Cannot open file: {e}"))?;

        let mut reader = BufReader::new(response.into_reader());
        let mut writer = BufWriter::new(&mut file);
        let mut buffer = [0u8; 8192];

        let mut total_bytes = downloaded;
        loop {
            let n = reader.read(&mut buffer).map_err(|e| format!("Read error: {e}"))?;
            if n == 0 {
                break;
            }
            writer.write_all(&buffer[..n]).map_err(|e| format!("Write error: {e}"))?;
            total_bytes += n as u64;
            progress_callback(DownloadProgress {
                component: component.to_string(),
                downloaded: total_bytes,
                total: config.size_bytes,
                percent: (total_bytes as f32 / config.size_bytes as f32) * 100.0,
            });
        }
        writer.flush().map_err(|e| format!("Flush error: {e}"))?;

        self.verify_checksum(&filename, &config.sha256)?;
        Ok(filename)
    }

    fn verify_checksum(&self, path: &Path, expected: &str) -> Result<(), String> {
        use sha2::{Digest, Sha256};

        let file = File::open(path).map_err(|e| format!("Cannot open file: {e}"))?;
        let mut reader = BufReader::new(file);
        let mut hasher = Sha256::new();
        let mut buffer = [0u8; 8192];

        loop {
            let n = reader.read(&mut buffer).map_err(|e| format!("Read error: {e}"))?;
            if n == 0 {
                break;
            }
            hasher.update(&buffer[..n]);
        }

        let computed = format!("{:x}", hasher.finalize());
        if computed == expected {
            Ok(())
        } else {
            Err(format!(
                "Checksum mismatch: expected {expected}, got {computed}"
            ))
        }
    }

    pub fn extract(&self, archive: &Path, dest: &Path) -> Result<(), String> {
        fs::create_dir_all(dest).map_err(|e| format!("Cannot create directory: {e}"))?;

        let file = File::open(archive).map_err(|e| format!("Cannot open archive: {e}"))?;
        let mut zip = zip::ZipArchive::new(file).map_err(|e| format!("Invalid zip: {e}"))?;

        for i in 0..zip.len() {
            let mut entry = zip.by_index(i).map_err(|e| format!("Cannot read entry: {e}"))?;
            let outpath = dest.join(entry.name());

            if entry.is_dir() {
                fs::create_dir_all(&outpath).map_err(|e| format!("Cannot create dir: {e}"))?;
            } else {
                if let Some(parent) = outpath.parent() {
                    fs::create_dir_all(parent).map_err(|e| format!("Cannot create parent: {e}"))?;
                }
                let mut outfile = File::create(&outpath).map_err(|e| format!("Cannot create file: {e}"))?;
                io::copy(&mut entry, &mut outfile).map_err(|e| format!("Cannot extract: {e}"))?;
            }
        }
        Ok(())
    }
}
