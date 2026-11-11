mod supervisor;
mod downloader;
mod bootstrap;

use std::sync::Mutex;
use supervisor::{ServiceStatus, Supervisor};
use bootstrap::Bootstrap;
use tauri::State;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::Command,
};

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let url = url.trim();
    if url.len() > 2048 || url.chars().any(|ch| ch.is_control()) {
        return Err("The external link is invalid.".to_string());
    }
    if !(url.starts_with("https://") || url.starts_with("http://") || url.starts_with("mailto:")) {
        return Err("Only HTTP, HTTPS, and mail links can be opened externally.".to_string());
    }

    // Pass the URL as a process argument, never through cmd.exe or a shell.
    Command::new("explorer.exe")
        .arg(url)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open the link in your default browser: {error}"))
}


#[derive(serde::Serialize)]
struct ClipDownloadTarget {
    path: String,
}

fn clip_download_root() -> Result<PathBuf, String> {
    let profile = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .ok_or_else(|| "Windows user profile directory is unavailable".to_string())?;
    let root = profile.join("Downloads").join("Clippy");
    fs::create_dir_all(&root)
        .map_err(|e| format!("Cannot create Clippy download folder {}: {e}", root.display()))?;
    root.canonicalize()
        .map_err(|e| format!("Cannot resolve Clippy download folder: {e}"))
}

fn resolve_clip_download_path(raw: &str) -> Result<PathBuf, String> {
    let candidate = PathBuf::from(raw);
    let file_name = candidate.file_name()
        .ok_or_else(|| "Download file path is invalid".to_string())?;
    let parent = candidate.parent()
        .ok_or_else(|| "Download folder is invalid".to_string())?
        .canonicalize()
        .map_err(|e| format!("Download folder is unavailable: {e}"))?;
    let root = clip_download_root()?;
    if parent != root {
        return Err("Downloads can only be written inside the Clippy download folder.".to_string());
    }
    if candidate.extension().and_then(|ext| ext.to_str()).map(|ext| ext.eq_ignore_ascii_case("mp4")) != Some(true) {
        return Err("Only MP4 clip downloads are supported.".to_string());
    }
    let resolved = parent.join(file_name);
    if fs::symlink_metadata(&resolved).map(|meta| meta.file_type().is_symlink()).unwrap_or(false) {
        return Err("The requested download path is not a regular file.".to_string());
    }
    Ok(resolved)
}

#[tauri::command]
fn begin_clip_download(filename: String) -> Result<ClipDownloadTarget, String> {
    let root = clip_download_root()?;
    let requested_stem = Path::new(&filename).file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or("clip");
    let mut stem: String = requested_stem.chars()
        .filter(|ch| ch.is_alphanumeric() || *ch == '-' || *ch == '_')
        .take(64)
        .collect();
    if stem.is_empty() {
        stem = "clip".to_string();
    }

    for suffix in 1..=9999 {
        let name = if suffix == 1 {
            format!("{stem}.mp4")
        } else {
            format!("{stem} ({suffix}).mp4")
        };
        let path = root.join(name);
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(_) => return Ok(ClipDownloadTarget { path: path.display().to_string() }),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("Cannot create download file {}: {error}", path.display())),
        }
    }
    Err("Could not find an available filename for this clip.".to_string())
}

#[tauri::command]
fn append_clip_download_chunk(path: String, bytes: Vec<u8>) -> Result<u64, String> {
    let path = resolve_clip_download_path(&path)?;
    let mut file = OpenOptions::new().append(true).open(&path)
        .map_err(|e| format!("Cannot open download file {}: {e}", path.display()))?;
    file.write_all(&bytes)
        .map_err(|e| format!("Cannot write download file {}: {e}", path.display()))?;
    file.metadata()
        .map(|metadata| metadata.len())
        .map_err(|e| format!("Cannot inspect download file: {e}"))
}

#[tauri::command]
fn finish_clip_download(path: String) -> Result<String, String> {
    let path = resolve_clip_download_path(&path)?;
    let file = OpenOptions::new().write(true).open(&path)
        .map_err(|e| format!("Cannot finalize download file {}: {e}", path.display()))?;
    file.sync_all()
        .map_err(|e| format!("Cannot flush download file {}: {e}", path.display()))?;
    if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
        return Err("The downloaded clip is empty.".to_string());
    }
    Ok(path.display().to_string())
}

#[tauri::command]
fn cancel_clip_download(path: String) -> Result<(), String> {
    let path = resolve_clip_download_path(&path)?;
    if path.exists() {
        fs::remove_file(&path)
            .map_err(|e| format!("Cannot remove incomplete download {}: {e}", path.display()))?;
    }
    Ok(())
}

#[tauri::command]
fn reveal_clip_download(path: String) -> Result<(), String> {
    let path = resolve_clip_download_path(&path)?;
    Command::new("explorer.exe")
        .arg(format!("/select,{}", path.display()))
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("Cannot open the download folder: {e}"))
}

#[tauri::command]
fn start_services(state: State<'_, Mutex<Supervisor>>) -> Result<ServiceStatus, String> {
    state.lock().map_err(|_| "Service supervisor is unavailable".to_string())?.start()
}

#[tauri::command]
fn stop_services(state: State<'_, Mutex<Supervisor>>) -> Result<ServiceStatus, String> {
    state.lock().map_err(|_| "Service supervisor is unavailable".to_string())?.stop()
}

#[tauri::command]
fn service_status(state: State<'_, Mutex<Supervisor>>) -> Result<ServiceStatus, String> {
    state.lock().map_err(|_| "Service supervisor is unavailable".to_string())?.status()
}

#[tauri::command]
fn check_runtime() -> Result<bootstrap::BootstrapStatus, String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let runtime_root = local.join("Clippy").join("runtime");

    // The manifest belongs to the per-user installation, never the developer checkout.
    let manifest_path = local.join("Clippy").join("runtime-manifest.json");
    let config = bootstrap::BootstrapConfig { runtime_root, manifest_path };

    let bootstrap = Bootstrap::new(config);
    bootstrap.get_status()
}


#[tauri::command]
fn install_app_payload(app: tauri::AppHandle) -> Result<String, String> {
    use std::{fs, path::PathBuf};
    use tauri::Manager;

    let local = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let app_root = local.join("Clippy").join("app");
    let current = app_root.join("current");
    let staging = app_root.join("current.installing");
    let backup = app_root.join("current.previous");
    use sha2::{Digest, Sha256};
    use std::io::Read;

    let resource_dir = app.path().resource_dir().map_err(|e| format!("Cannot locate installer resources: {e}"))?;
    let archive_path = resource_dir.join("app-payload.zip");
    let digest_path = resource_dir.join("app-payload.sha256");
    if !archive_path.is_file() || !digest_path.is_file() {
        return Err("Bundled application payload or its SHA-256 manifest is missing.".to_string());
    }
    let expected_hash = fs::read_to_string(&digest_path)
        .map_err(|e| format!("Cannot read payload digest: {e}"))?
        .trim()
        .to_ascii_lowercase();
    if expected_hash.len() != 64 || !expected_hash.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("Bundled application payload digest is malformed.".to_string());
    }

    if current.join(".clippy-payload-sha256").is_file()
        && fs::read_to_string(current.join(".clippy-payload-sha256")).ok().map(|v| v.trim().to_string()).as_deref() == Some(expected_hash.as_str())
        && current.join("app.py").is_file()
        && current.join("render-service").join("dist").join("server.js").is_file()
        && current.join("remotion").join("src").join("index.ts").is_file()
        && current.join("setup-runtime.ps1").is_file()
    {
        return Ok(current.display().to_string());
    }
    if !archive_path.is_file() {
        return Err(format!("Bundled application payload is missing: {}", archive_path.display()));
    }

    fs::create_dir_all(&app_root).map_err(|e| format!("Cannot create application directory: {e}"))?;
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| format!("Cannot clear incomplete setup directory: {e}"))?;
    }
    fs::create_dir_all(&staging).map_err(|e| format!("Cannot create setup directory: {e}"))?;

    let mut archive_file = fs::File::open(&archive_path).map_err(|e| format!("Cannot open application payload: {e}"))?;
    let mut hasher = Sha256::new();
    let mut hash_buffer = [0u8; 64 * 1024];
    loop {
        let count = archive_file.read(&mut hash_buffer).map_err(|e| format!("Cannot read application payload: {e}"))?;
        if count == 0 { break; }
        hasher.update(&hash_buffer[..count]);
    }
    let actual_hash = format!("{:x}", hasher.finalize());
    if actual_hash != expected_hash {
        return Err("Bundled application payload failed SHA-256 verification.".to_string());
    }
    drop(archive_file);
    let archive = fs::File::open(&archive_path).map_err(|e| format!("Cannot reopen application payload: {e}"))?;
    let mut zip = zip::ZipArchive::new(archive).map_err(|e| format!("Application payload is invalid: {e}"))?;
    zip.extract(&staging).map_err(|e| format!("Cannot extract application payload: {e}"))?;

    for relative in ["app.py", "render-service/dist/server.js", "remotion/src/index.ts", "setup-runtime.ps1"] {
        if !staging.join(relative).is_file() {
            let _ = fs::remove_dir_all(&staging);
            return Err(format!("Application payload is incomplete; missing {relative}"));
        }
    }

    if backup.exists() {
        fs::remove_dir_all(&backup).map_err(|e| format!("Cannot remove previous application backup: {e}"))?;
    }
    let had_current = current.exists();
    if had_current {
        fs::rename(&current, &backup).map_err(|e| format!("Cannot preserve current application before update: {e}"))?;
    }
    if let Err(error) = fs::rename(&staging, &current) {
        if had_current {
            let _ = fs::rename(&backup, &current);
        }
        let _ = fs::remove_dir_all(&staging);
        return Err(format!("Cannot activate application payload: {error}"));
    }
    if backup.exists() {
        let _ = fs::remove_dir_all(&backup);
    }
    fs::write(current.join(".clippy-payload-sha256"), expected_hash)
        .map_err(|e| format!("Cannot write application payload marker: {e}"))?;

    Ok(current.display().to_string())
}


#[tauri::command]
async fn setup_runtime(app: tauri::AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || setup_runtime_blocking(app))
        .await
        .map_err(|e| format!("Runtime setup worker failed: {e}"))?
}

fn setup_runtime_blocking(app: tauri::AppHandle) -> Result<String, String> {
    use std::{
        io::{BufRead, BufReader, Write},
        process::Stdio,
        sync::mpsc,
        thread,
    };
    use tauri::Emitter;

    let local = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let root = local.join("Clippy");
    let script = root.join("app").join("current").join("setup-runtime.ps1");
    if !script.is_file() {
        return Err(format!("Runtime setup script is missing: {}", script.display()));
    }

    let log_dir = root.join("logs");
    std::fs::create_dir_all(&log_dir)
        .map_err(|e| format!("Cannot create runtime setup log directory: {e}"))?;
    let log_path = log_dir.join("runtime-setup.log");
    let mut log = std::fs::OpenOptions::new()
        .create(true).append(true).open(&log_path)
        .map_err(|e| format!("Cannot open runtime setup log {}: {e}", log_path.display()))?;
    writeln!(log, "\n===== Clippy in-app runtime setup: {} =====", chrono_free_timestamp())
        .map_err(|e| format!("Cannot write runtime setup log: {e}"))?;

    let mut command = Command::new("powershell.exe");
    command.args(["-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(&script)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let mut child = command.spawn()
        .map_err(|e| format!("Could not start the private runtime setup engine: {e}"))?;
    let stdout = child.stdout.take().ok_or("Could not capture setup output")?;
    let stderr = child.stderr.take().ok_or("Could not capture setup errors")?;
    let (tx, rx) = mpsc::channel::<(String, String)>();
    // ChildStdout and ChildStderr are distinct types, so drain them on
    // separate reader threads. Both must be drained concurrently to avoid
    // deadlocking when either pipe fills.
    let stdout_tx = tx.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().flatten() {
            if stdout_tx.send(("stdout".to_string(), line)).is_err() { break; }
        }
    });
    let stderr_tx = tx.clone();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().flatten() {
            if stderr_tx.send(("stderr".to_string(), line)).is_err() { break; }
        }
    });
    drop(tx);

    let mut recent = Vec::new();
    for (stream_name, line) in rx {
        let _ = writeln!(log, "[{stream_name}] {line}");
        let _ = log.flush();
        if recent.len() >= 80 { recent.remove(0); }
        recent.push(line.clone());
        let stage = line.split("[Clippy setup] ").nth(1).unwrap_or(&line).to_string();
        let _ = app.emit("clippy://runtime-setup-progress", serde_json::json!({
            "stage": stage,
            "stream": stream_name,
            "logPath": log_path.to_string_lossy()
        }));
    }

    let status = child.wait().map_err(|e| format!("Could not finish runtime setup: {e}"))?;
    if !status.success() {
        let details = recent.join("\n");
        let _ = app.emit("clippy://runtime-setup-progress", serde_json::json!({
            "stage": "Setup failed. Open diagnostics for details.",
            "failed": true,
            "logPath": log_path.to_string_lossy()
        }));
        return Err(format!("Runtime setup failed ({status}).\n{details}\nFull diagnostic log: {}", log_path.display()));
    }
    let _ = app.emit("clippy://runtime-setup-progress", serde_json::json!({
        "stage": "Runtime installation complete. Verifying components…",
        "complete": true,
        "logPath": log_path.to_string_lossy()
    }));
    Ok(format!("Runtime setup completed. Log: {}", log_path.display()))
}

fn chrono_free_timestamp() -> String {
    // Avoid another dependency; the log header is informational.
    format!("{:?}", std::time::SystemTime::now())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Supervisor::default()))
        .invoke_handler(tauri::generate_handler![
            start_services,
            stop_services,
            service_status,
            check_runtime,
            install_app_payload,
            setup_runtime,
            open_external_url,
            begin_clip_download,
            append_clip_download_chunk,
            finish_clip_download,
            cancel_clip_download,
            reveal_clip_download
        ])
        .run(tauri::generate_context!())
        .expect("error while running Clippy desktop application");
}
