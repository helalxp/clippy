mod supervisor;
mod downloader;
mod bootstrap;

use std::sync::Mutex;
use supervisor::{ServiceStatus, Supervisor};
use bootstrap::Bootstrap;
use tauri::State;
use std::process::Command;

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
fn setup_runtime() -> Result<String, String> {
    let local = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let script = local.join("Clippy").join("app").join("current").join("setup-runtime.ps1");
    if !script.is_file() {
        return Err(format!("Runtime setup script is missing: {}", script.display()));
    }

    let output = Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(&script)
        .output()
        .map_err(|e| format!("Could not launch the runtime installer: {e}"))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !output.status.success() {
        return Err(format!(
            "Runtime setup failed ({}).\n{}\n{}",
            output.status,
            stdout,
            stderr
        ));
    }
    Ok(stdout.into_owned())
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
            setup_runtime
        ])
        .run(tauri::generate_context!())
        .expect("error while running Clippy desktop application");
}
