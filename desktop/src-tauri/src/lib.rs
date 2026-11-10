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
    let app_version = env!("CARGO_PKG_VERSION");

    if current.join(".clippy-app-version").is_file()
        && fs::read_to_string(current.join(".clippy-app-version")).ok().as_deref() == Some(app_version)
        && current.join("app.py").is_file()
        && current.join("render-service").join("dist").join("server.js").is_file()
        && current.join("remotion").join("src").join("index.ts").is_file()
    {
        return Ok(current.display().to_string());
    }

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
    fs::write(current.join(".clippy-app-version"), app_version)
        .map_err(|e| format!("Cannot write application version marker: {e}"))?;

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
