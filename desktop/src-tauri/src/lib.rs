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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Supervisor::default()))
        .invoke_handler(tauri::generate_handler![
            start_services,
            stop_services,
            service_status,
            check_runtime
        ])
        .run(tauri::generate_context!())
        .expect("error while running Clippy desktop application");
}
