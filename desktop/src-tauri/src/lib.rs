mod supervisor;

use std::sync::Mutex;
use supervisor::{ServiceStatus, Supervisor};
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::new(Supervisor::default()))
        .invoke_handler(tauri::generate_handler![start_services, stop_services, service_status])
        .run(tauri::generate_context!())
        .expect("error while running Clippy desktop application");
}
