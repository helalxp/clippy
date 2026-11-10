mod supervisor;
mod downloader;
mod bootstrap;

use std::sync::Mutex;
use supervisor::{ServiceStatus, Supervisor};
use bootstrap::Bootstrap;
use tauri::State;

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

    let resource_dir = app.path().resource_dir().map_err(|e| format!("Cannot locate installer resources: {e}"))?;
    let archive_path = resource_dir.join("app-payload.zip");
    if !archive_path.is_file() {
        return Err(format!("Bundled application payload is missing: {}", archive_path.display()));
    }

    fs::create_dir_all(&app_root).map_err(|e| format!("Cannot create application directory: {e}"))?;
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| format!("Cannot clear incomplete setup directory: {e}"))?;
    }
    fs::create_dir_all(&staging).map_err(|e| format!("Cannot create setup directory: {e}"))?;

    let archive = fs::File::open(&archive_path).map_err(|e| format!("Cannot open application payload: {e}"))?;
    let mut zip = zip::ZipArchive::new(archive).map_err(|e| format!("Application payload is invalid: {e}"))?;
    zip.extract(&staging).map_err(|e| format!("Cannot extract application payload: {e}"))?;

    for relative in ["app.py", "render-service/dist/server.js", "remotion/src/index.ts"] {
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

    Ok(current.display().to_string())
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
            install_app_payload
        ])
        .run(tauri::generate_context!())
        .expect("error while running Clippy desktop application");
}
