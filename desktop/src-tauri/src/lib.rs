mod bootstrap;
mod data_storage;
mod installation;
mod supervisor;

static INSTALL_OPERATION: Mutex<()> = Mutex::new(());

#[derive(Default)]
struct SetupLifecycle {
    job: Option<supervisor::ProcessJob>,
    exiting: bool,
}

use bootstrap::Bootstrap;
use std::sync::Mutex;
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};
use supervisor::{ServiceStatus, Supervisor};
use tauri::{Emitter, Manager};



#[derive(Clone, serde::Serialize)]
struct StorageMoveProgress {
    stage: String,
    progress: f64,
    copied_bytes: u64,
    total_bytes: u64,
}

#[derive(serde::Serialize)]
struct StorageMoveResult {
    data_directory: String,
    previous_location_removed: bool,
}

fn emit_storage_move_progress(
    app: &tauri::AppHandle,
    stage: &str,
    copied_bytes: u64,
    total_bytes: u64,
) {
    let progress = if total_bytes == 0 {
        if matches!(stage, "starting" | "complete") { 100.0 } else { 0.0 }
    } else {
        (copied_bytes as f64 / total_bytes as f64 * 100.0).clamp(0.0, 100.0)
    };
    let _ = app.emit(
        "clippy://data-move-progress",
        StorageMoveProgress {
            stage: stage.to_string(),
            progress,
            copied_bytes,
            total_bytes,
        },
    );
}

#[tauri::command]
async fn choose_data_directory(current_path: Option<String>) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || choose_data_directory_blocking(current_path))
        .await
        .map_err(|error| format!("Folder picker worker failed: {error}"))?
}

fn choose_data_directory_blocking(current_path: Option<String>) -> Result<Option<String>, String> {
    #[cfg(windows)]
    {
        let initial = current_path
            .map(PathBuf::from)
            .and_then(|path| path.parent().map(Path::to_path_buf))
            .unwrap_or_default();
        let script = r#"
            [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'Choose an empty folder for Clippy data'
            $dialog.ShowNewFolderButton = $true
            $dialog.SelectedPath = $env:CLIPPY_PICKER_INITIAL
            if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
                [Console]::WriteLine($dialog.SelectedPath)
            }
        "#;
        let mut command = Command::new("powershell.exe");
        command.env("CLIPPY_PICKER_INITIAL", initial);
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-STA",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let output = command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|error| format!("Could not open the Windows folder picker: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "The Windows folder picker failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        let selected = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if selected.is_empty() {
            return Ok(None);
        }
        let path = PathBuf::from(selected);
        if !path.is_absolute() {
            return Err("The selected destination must be an absolute Windows path.".into());
        }
        Ok(Some(path.to_string_lossy().into_owned()))
    }
    #[cfg(not(windows))]
    {
        let _ = current_path;
        Err("Changing the Clippy data location is currently supported on Windows desktop only.".into())
    }
}

#[tauri::command]
async fn move_data_directory(
    app: tauri::AppHandle,
    destination: String,
) -> Result<StorageMoveResult, String> {
    tauri::async_runtime::spawn_blocking(move || {
        move_data_directory_blocking(app, destination)
    })
    .await
    .map_err(|error| format!("Storage move worker failed: {error}"))?
}

fn move_data_directory_blocking(
    app: tauri::AppHandle,
    destination: String,
) -> Result<StorageMoveResult, String> {
    let _operation = INSTALL_OPERATION
        .lock()
        .map_err(|_| "Installation worker unavailable")?;
    let install_root = installation::user_root()?;
    let _installation = installation::InstallationLock::acquire(&install_root, "Install", 300_000)?;

    let state = app.state::<Mutex<Supervisor>>();
    let mut supervisor = state
        .lock()
        .map_err(|_| "Service supervisor is unavailable")?;
    let current = supervisor.data_directory()?;
    let (source, destination) =
        data_storage::validate_destination(&current, Path::new(destination.trim()))?;
    data_storage::validate_destination_outside_install_root(&install_root, &destination)?;
    let staging = data_storage::staging_path(&destination)?;

    // The backend atomically rejects new mutations and refuses this handshake
    // while any generation job or upload is still active.
    supervisor.prepare_data_move()?;
    supervisor.stop()?;

    emit_storage_move_progress(&app, "copying", 0, 0);
    let mut last_reported_percent = 0u64;
    let mut last_reported_at = std::time::Instant::now();
    if let Err(error) = data_storage::copy_tree_verified(
        &source,
        &staging,
        |copied_bytes, total_bytes| {
            let percent = if total_bytes == 0 {
                0
            } else {
                (copied_bytes.saturating_mul(100) / total_bytes).min(100)
            };
            if percent > last_reported_percent
                || last_reported_at.elapsed() >= std::time::Duration::from_millis(250)
                || copied_bytes == total_bytes
            {
                emit_storage_move_progress(&app, "copying", copied_bytes, total_bytes);
                last_reported_percent = percent;
                last_reported_at = std::time::Instant::now();
            }
        },
    ) {
        let _ = data_storage::remove_tree(&staging);
        let restart = supervisor.start();
        return Err(match restart {
            Ok(_) => format!("Data move was cancelled safely: {error}"),
            Err(restart_error) => format!(
                "Data move failed: {error}. Clippy could not restart from the original location: {restart_error}"
            ),
        });
    }

    if let Err(error) = data_storage::activate_staged_directory(&staging, &destination) {
        let _ = data_storage::remove_tree(&staging);
        let restart = supervisor.start();
        return Err(match restart {
            Ok(_) => format!("Data move was not activated: {error}"),
            Err(restart_error) => format!(
                "Data move was not activated: {error}. Clippy could not restart from the original location: {restart_error}"
            ),
        });
    }

    if let Err(error) = data_storage::write_config(&install_root, &destination) {
        // Keep the verified destination copy as a recovery copy. The original
        // configuration remains active because the config write is atomic.
        let restart = supervisor.start();
        return Err(match restart {
            Ok(_) => format!(
                "Could not save the new data location: {error}. The original location remains active and the complete copy is preserved at {}.",
                destination.display()
            ),
            Err(restart_error) => format!(
                "Could not save the new data location: {error}. The complete copy is preserved at {}. Clippy could not restart from the original location: {restart_error}",
                destination.display()
            ),
        });
    }

    emit_storage_move_progress(&app, "starting", 100, 100);
    if let Err(error) = supervisor.start() {
        let _ = supervisor.stop();
        let restore_config = data_storage::write_config(&install_root, &source);
        let restore_services = supervisor.start();
        let rollback_details = match (restore_config, restore_services) {
            (Ok(()), Ok(_)) => "The previous location has been restored and Clippy services restarted.".to_string(),
            (config, services) => format!(
                "Rollback needs attention (configuration: {}; services: {}). The original data was not deleted.",
                config.err().unwrap_or_else(|| "restored".into()),
                services.err().unwrap_or_else(|| "running".into())
            ),
        };
        return Err(format!("Clippy could not start from the new data location: {error}. {rollback_details}"));
    }

    // Only remove the old copy after the backend and renderer are healthy from
    // the new location. A cleanup failure leaves a harmless duplicate, never a
    // partially moved Library.
    let previous_location_removed = data_storage::remove_tree(&source).is_ok();
    emit_storage_move_progress(&app, "complete", 100, 100);
    Ok(StorageMoveResult {
        data_directory: destination.to_string_lossy().into_owned(),
        previous_location_removed,
    })
}


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
    fs::create_dir_all(&root).map_err(|e| {
        format!(
            "Cannot create Clippy download folder {}: {e}",
            root.display()
        )
    })?;
    root.canonicalize()
        .map_err(|e| format!("Cannot resolve Clippy download folder: {e}"))
}

fn library_root() -> Result<PathBuf, String> {
    let install_root = installation::user_root()?;
    let data_root = data_storage::configured_data_directory(&install_root)?;
    Ok(data_root.join("library"))
}

fn resolve_library_path(raw: &str) -> Result<PathBuf, String> {
    let root = library_root()?.canonicalize()
        .map_err(|error| format!("Library folder is unavailable: {error}"))?;
    let target = PathBuf::from(raw).canonicalize()
        .map_err(|error| format!("Library item is unavailable: {error}"))?;
    if !target.starts_with(&root) {
        return Err("The requested path is outside the Clippy Library.".to_string());
    }
    Ok(target)
}

#[tauri::command]
fn reveal_library_path(path: String) -> Result<(), String> {
    let target = resolve_library_path(&path)?;
    let mut command = Command::new("explorer.exe");
    if target.is_file() {
        command.arg(format!("/select,{}", target.display()));
    } else {
        command.arg(&target);
    }
    command.spawn().map(|_| ())
        .map_err(|error| format!("Cannot open the Library location in File Explorer: {error}"))
}

fn resolve_any_download_path(raw: &str) -> Result<PathBuf, String> {
    let requested = PathBuf::from(raw);
    let name = requested.file_name()
        .ok_or_else(|| "Download file path is invalid".to_string())?;
    let parent = requested.parent()
        .ok_or_else(|| "Download folder is invalid".to_string())?
        .canonicalize()
        .map_err(|error| format!("Download folder is unavailable: {error}"))?;
    let download_root = clip_download_root()?.canonicalize()
        .map_err(|error| format!("Clippy download folder is unavailable: {error}"))?;
    if parent != download_root {
        return Err("Downloads can only be written inside the Clippy download folder.".to_string());
    }
    let extension = requested.extension().and_then(|value| value.to_str()).unwrap_or("").to_ascii_lowercase();
    if !matches!(extension.as_str(), "mp4" | "zip") {
        return Err("Only MP4 and ZIP downloads are supported.".to_string());
    }
    let target = parent.join(name);
    if fs::symlink_metadata(&target).map(|metadata| metadata.file_type().is_symlink()).unwrap_or(false) {
        return Err("The requested download target is not a regular file.".to_string());
    }
    Ok(target)
}

#[tauri::command]
fn begin_file_download(filename: String) -> Result<ClipDownloadTarget, String> {
    let root = clip_download_root()?;
    let requested = Path::new(&filename);
    let extension = requested.extension().and_then(|value| value.to_str()).unwrap_or("").to_ascii_lowercase();
    if !matches!(extension.as_str(), "mp4" | "zip") {
        return Err("Only MP4 and ZIP downloads are supported.".to_string());
    }
    let requested_stem = requested.file_stem().and_then(|value| value.to_str()).unwrap_or("clippy-export");
    let mut stem: String = requested_stem.chars()
        .filter(|character| character.is_alphanumeric() || *character == '-' || *character == '_' || *character == ' ')
        .take(100)
        .collect();
    stem = stem.trim().trim_matches('.').to_string();
    if stem.is_empty() {
        stem = "clippy-export".to_string();
    }
    let upper = stem.to_ascii_uppercase();
    if matches!(upper.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (upper.len() == 4
            && (upper.starts_with("COM") || upper.starts_with("LPT"))
            && upper.as_bytes()[3].is_ascii_digit()
            && upper.as_bytes()[3] != b'0')
    {
        stem = format!("Clippy-{stem}");
    }
    for suffix in 1..=9999 {
        let name = if suffix == 1 { format!("{stem}.{extension}") }
            else { format!("{stem} ({suffix}).{extension}") };
        let target = root.join(name);
        match OpenOptions::new().write(true).create_new(true).open(&target) {
            Ok(_) => return Ok(ClipDownloadTarget { path: target.display().to_string() }),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("Cannot create download {}: {error}", target.display())),
        }
    }
    Err("Could not find an available filename for this download.".to_string())
}

#[tauri::command]
fn append_file_download_chunk(path: String, bytes: Vec<u8>) -> Result<u64, String> {
    let target = resolve_any_download_path(&path)?;
    let mut file = OpenOptions::new().append(true).open(&target)
        .map_err(|error| format!("Cannot open download {}: {error}", target.display()))?;
    file.write_all(&bytes)
        .map_err(|error| format!("Cannot write download {}: {error}", target.display()))?;
    file.metadata().map(|metadata| metadata.len())
        .map_err(|error| format!("Cannot inspect download {}: {error}", target.display()))
}

#[tauri::command]
fn finish_file_download(path: String) -> Result<String, String> {
    let target = resolve_any_download_path(&path)?;
    let file = OpenOptions::new().write(true).open(&target)
        .map_err(|error| format!("Cannot finalize download {}: {error}", target.display()))?;
    file.sync_all().map_err(|error| format!("Cannot flush download {}: {error}", target.display()))?;
    if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
        return Err("The downloaded file is empty.".to_string());
    }
    Ok(target.display().to_string())
}

#[tauri::command]
fn cancel_file_download(path: String) -> Result<(), String> {
    let target = resolve_any_download_path(&path)?;
    if target.exists() {
        fs::remove_file(&target)
            .map_err(|error| format!("Cannot remove incomplete download {}: {error}", target.display()))?;
    }
    Ok(())
}

#[tauri::command]
fn reveal_file_download(path: String) -> Result<(), String> {
    let target = resolve_any_download_path(&path)?;
    Command::new("explorer.exe")
        .arg(format!("/select,{}", target.display()))
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Cannot reveal downloaded file: {error}"))
}

#[tauri::command]
async fn start_services(app: tauri::AppHandle) -> Result<ServiceStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let _operation = INSTALL_OPERATION
            .lock()
            .map_err(|_| "Installation worker unavailable")?;
        let root = installation::user_root()?;
        let _installation = installation::InstallationLock::acquire(&root, "Install", 300_000)?;
        let state = app.state::<Mutex<Supervisor>>();
        let result = state
            .lock()
            .map_err(|_| "Service supervisor is unavailable".to_string())?
            .start();
        result
    })
    .await
    .map_err(|e| format!("Service startup worker failed: {e}"))?
}

#[tauri::command]
async fn prepare_update_install(app: tauri::AppHandle) -> Result<ServiceStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let _operation = INSTALL_OPERATION
            .lock()
            .map_err(|_| "Installation worker unavailable")?;
        let root = installation::user_root()?;
        let _installation = installation::InstallationLock::acquire(&root, "Install", 300_000)?;
        let state = app.state::<Mutex<Supervisor>>();
        let mut supervisor = state
            .lock()
            .map_err(|_| "Service supervisor is unavailable".to_string())?;

        // The backend atomically blocks new work and confirms that existing
        // requests, jobs, uploads, and publications have settled before either
        // managed process is stopped for the Windows installer.
        supervisor.prepare_update()?;
        supervisor.stop()
    })
    .await
    .map_err(|error| format!("Update preparation worker failed: {error}"))?
}

#[tauri::command]
async fn restore_services_after_update_failure(
    app: tauri::AppHandle,
) -> Result<ServiceStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let _operation = INSTALL_OPERATION
            .lock()
            .map_err(|_| "Installation worker unavailable")?;
        let root = installation::user_root()?;
        let _installation = installation::InstallationLock::acquire(&root, "Install", 300_000)?;
        let state = app.state::<Mutex<Supervisor>>();
        state
            .lock()
            .map_err(|_| "Service supervisor is unavailable".to_string())?
            .start()
    })
    .await
    .map_err(|error| format!("Service recovery worker failed: {error}"))?
}

#[tauri::command]
fn get_api_token(app: tauri::AppHandle) -> Result<String, String> {
    let state = app.state::<Mutex<Supervisor>>();
    let result = state
        .lock()
        .map_err(|_| "Service supervisor is unavailable".to_string())?
        .api_token();
    result
}

#[tauri::command]
async fn stop_services(app: tauri::AppHandle) -> Result<ServiceStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Mutex<Supervisor>>();
        let result = state
            .lock()
            .map_err(|_| "Service supervisor is unavailable".to_string())?
            .stop();
        result
    })
    .await
    .map_err(|e| format!("Service shutdown worker failed: {e}"))?
}

#[tauri::command]
async fn service_status(app: tauri::AppHandle) -> Result<ServiceStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Mutex<Supervisor>>();
        let result = state
            .lock()
            .map_err(|_| "Service supervisor is unavailable".to_string())?
            .status();
        result
    })
    .await
    .map_err(|e| format!("Service status worker failed: {e}"))?
}

#[tauri::command]
async fn check_runtime() -> Result<bootstrap::BootstrapStatus, String> {
    tauri::async_runtime::spawn_blocking(check_runtime_blocking)
        .await
        .map_err(|e| format!("Runtime validation worker failed: {e}"))?
}

fn check_runtime_blocking() -> Result<bootstrap::BootstrapStatus, String> {
    let _operation = INSTALL_OPERATION
        .lock()
        .map_err(|_| "Installation worker unavailable")?;
    let root = installation::user_root()?;
    let _installation = installation::InstallationLock::acquire(&root, "Install", 300_000)?;
    let local = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let install_root = local.join("Clippy");
    let runtime_root = install_root.join("runtime");
    let data_root = data_storage::configured_data_directory(&install_root)?;

    // The manifest belongs to the per-user installation, never the developer checkout.
    let manifest_path = install_root.join("runtime-manifest.json");
    let config = bootstrap::BootstrapConfig {
        runtime_root,
        manifest_path,
        data_root,
    };

    let bootstrap = Bootstrap::new(config);
    bootstrap.get_status()
}

#[tauri::command]
async fn install_app_payload(app: tauri::AppHandle) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || install_app_payload_blocking(app))
        .await
        .map_err(|e| format!("Application payload worker failed: {e}"))?
}

fn install_app_payload_blocking(app: tauri::AppHandle) -> Result<String, String> {
    let _operation = INSTALL_OPERATION
        .lock()
        .map_err(|_| "Installation worker unavailable")?;
    let root = installation::user_root()?;
    let _installation = installation::InstallationLock::acquire(&root, "Install", 300_000)?;
    {
        let state = app.state::<Mutex<Supervisor>>();
        state
            .lock()
            .map_err(|_| "Service supervisor unavailable")?
            .stop()?;
    }
    installation::preserve_references(&root)?;
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

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Cannot locate installer resources: {e}"))?;
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

    let required_payload_files = [
        "app.py",
        "requirements.txt",
        "VERSION",
        "setup-runtime.ps1",
        "runtime-archive.ps1",
        "runtime-manifest-state.ps1",
        "runtime-contract.json",
        "runtime-health.ps1",
        "render-service/dist/server.js",
        "render-service/node_modules/@remotion/renderer/package.json",
        "remotion/src/index.ts",
        "bgutil-provider/server/build/generate_once.js",
    ];
    let current_payload_is_complete = required_payload_files
        .iter()
        .all(|relative| current.join(relative).is_file());
    if current.join(".clippy-payload-sha256").is_file()
        && fs::read_to_string(current.join(".clippy-payload-sha256"))
            .ok()
            .map(|v| v.trim().to_string())
            .as_deref()
            == Some(expected_hash.as_str())
        && current_payload_is_complete
    {
        return Ok(current.display().to_string());
    }
    if !archive_path.is_file() {
        return Err(format!(
            "Bundled application payload is missing: {}",
            archive_path.display()
        ));
    }

    fs::create_dir_all(&app_root)
        .map_err(|e| format!("Cannot create application directory: {e}"))?;
    // Recover an interrupted upgrade before starting another one. The old
    // payload is code, not user data, but keeping it available avoids leaving
    // the installation without a launchable app if the previous process died
    // between the two directory renames.
    if !current.exists() && backup.exists() {
        fs::rename(&backup, &current)
            .map_err(|e| format!("Cannot restore the previous application payload: {e}"))?;
    }
    if staging.exists() {
        fs::remove_dir_all(&staging)
            .map_err(|e| format!("Cannot clear incomplete setup directory: {e}"))?;
    }
    fs::create_dir_all(&staging).map_err(|e| format!("Cannot create setup directory: {e}"))?;

    let mut archive_file = fs::File::open(&archive_path)
        .map_err(|e| format!("Cannot open application payload: {e}"))?;
    let mut hasher = Sha256::new();
    let mut hash_buffer = [0u8; 64 * 1024];
    loop {
        let count = archive_file
            .read(&mut hash_buffer)
            .map_err(|e| format!("Cannot read application payload: {e}"))?;
        if count == 0 {
            break;
        }
        hasher.update(&hash_buffer[..count]);
    }
    let actual_hash = format!("{:x}", hasher.finalize());
    if actual_hash != expected_hash {
        return Err("Bundled application payload failed SHA-256 verification.".to_string());
    }
    drop(archive_file);
    let archive = fs::File::open(&archive_path)
        .map_err(|e| format!("Cannot reopen application payload: {e}"))?;
    let mut zip = zip::ZipArchive::new(archive)
        .map_err(|e| format!("Application payload is invalid: {e}"))?;
    zip.extract(&staging)
        .map_err(|e| format!("Cannot extract application payload: {e}"))?;

    for relative in required_payload_files {
        if !staging.join(relative).is_file() {
            let _ = fs::remove_dir_all(&staging);
            return Err(format!(
                "Application payload is incomplete; missing {relative}"
            ));
        }
    }
    // Store the verified payload identity inside staging so it becomes active
    // atomically with the files it describes.
    fs::write(
        staging.join(".clippy-payload-sha256"),
        expected_hash.as_bytes(),
    )
    .map_err(|e| format!("Cannot write staged application payload marker: {e}"))?;

    if backup.exists() {
        fs::remove_dir_all(&backup)
            .map_err(|e| format!("Cannot remove previous application backup: {e}"))?;
    }
    let had_current = current.exists();
    if had_current {
        fs::rename(&current, &backup)
            .map_err(|e| format!("Cannot preserve current application before update: {e}"))?;
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
    let _operation = INSTALL_OPERATION
        .lock()
        .map_err(|_| "Installation worker unavailable")?;
    {
        let state = app.state::<Mutex<Supervisor>>();
        state
            .lock()
            .map_err(|_| "Service supervisor unavailable")?
            .stop()?;
    }

    let local = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .ok_or_else(|| "LOCALAPPDATA not found".to_string())?;
    let root = local.join("Clippy");
    let script = root.join("app").join("current").join("setup-runtime.ps1");
    if !script.is_file() {
        return Err(format!(
            "Runtime setup script is missing: {}",
            script.display()
        ));
    }

    let log_dir = root.join("logs");
    std::fs::create_dir_all(&log_dir)
        .map_err(|e| format!("Cannot create runtime setup log directory: {e}"))?;
    let log_path = log_dir.join("runtime-setup.log");
    let mut log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("Cannot open runtime setup log {}: {e}", log_path.display()))?;
    writeln!(
        log,
        "\n===== Clippy in-app runtime setup: {} =====",
        chrono_free_timestamp()
    )
    .map_err(|e| format!("Cannot write runtime setup log: {e}"))?;

    let mut command = Command::new("powershell.exe");
    command
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(&script)
        // The desktop app may itself be launched from PowerShell 7. Remove its
        // module path before starting Windows PowerShell 5.1 so the legacy host
        // initializes its own compatible modules instead of inheriting PS7 paths.
        .env_remove("PSModulePath")
        .env("CLIPPY_SETUP_WAIT_STDIN", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    let lifecycle = app.state::<Mutex<SetupLifecycle>>();
    let mut setup = lifecycle
        .lock()
        .map_err(|_| "Setup lifecycle unavailable")?;
    if setup.exiting {
        return Err("Clippy is shutting down.".into());
    }
    let job = supervisor::ProcessJob::new()?;
    let mut child = command
        .spawn()
        .map_err(|e| format!("Could not start the private runtime setup engine: {e}"))?;
    if let Err(error) = job.assign(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    setup.job = Some(job);
    // The script waits before touching disk, so no descendant can escape the
    // job during the interval between CreateProcess and job assignment.
    let release = child
        .stdin
        .take()
        .ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::BrokenPipe, "Setup input unavailable")
        })
        .and_then(|mut input| input.write_all(b"GO\n"));
    if let Err(error) = release {
        setup.job.take();
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!("Could not release runtime setup: {error}"));
    }
    drop(setup);
    let stdout = child
        .stdout
        .take()
        .ok_or("Could not capture setup output")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Could not capture setup errors")?;
    let (tx, rx) = mpsc::channel::<(String, String)>();
    // ChildStdout and ChildStderr are distinct types, so drain them on
    // separate reader threads. Both must be drained concurrently to avoid
    // deadlocking when either pipe fills.
    let stdout_tx = tx.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().flatten() {
            if stdout_tx.send(("stdout".to_string(), line)).is_err() {
                break;
            }
        }
    });
    let stderr_tx = tx.clone();
    thread::spawn(move || {
        for line in BufReader::new(stderr).lines().flatten() {
            if stderr_tx.send(("stderr".to_string(), line)).is_err() {
                break;
            }
        }
    });
    drop(tx);

    let mut recent = Vec::new();
    for (stream_name, line) in rx {
        let _ = writeln!(log, "[{stream_name}] {line}");
        let _ = log.flush();
        if recent.len() >= 80 {
            recent.remove(0);
        }
        recent.push(line.clone());
        let stage = line
            .split("[Clippy setup] ")
            .nth(1)
            .unwrap_or(&line)
            .to_string();
        let mut component: Option<String> = None;
        let mut progress: Option<f32> = None;
        if let Some(rest) = stage.strip_prefix("Downloading ") {
            component = Some(rest.split(';').next().unwrap_or(rest).to_string());
            progress = Some(0.0);
        }
        if let Some((name, rest)) = stage.split_once(": ") {
            if let Some((value, _)) = rest.split_once('%') {
                if let Ok(parsed) = value.trim().parse::<f32>() {
                    component = Some(name.to_string());
                    progress = Some(parsed.clamp(0.0, 100.0));
                }
            }
        }
        let _ = app.emit(
            "clippy://runtime-setup-progress",
            serde_json::json!({
                "stage": stage,
                "component": component,
                "progress": progress,
                "stream": stream_name,
                "logPath": log_path.to_string_lossy()
            }),
        );
    }

    let status = child
        .wait()
        .map_err(|e| format!("Could not finish runtime setup: {e}"))?;
    lifecycle
        .lock()
        .map_err(|_| "Setup lifecycle unavailable")?
        .job
        .take();
    if !status.success() {
        let details = recent.join("\n");
        let _ = app.emit(
            "clippy://runtime-setup-progress",
            serde_json::json!({
                "stage": "Setup failed. Open diagnostics for details.",
                "failed": true,
                "logPath": log_path.to_string_lossy()
            }),
        );
        return Err(format!(
            "Runtime setup failed ({status}).\n{details}\nFull diagnostic log: {}",
            log_path.display()
        ));
    }
    let _ = app.emit(
        "clippy://runtime-setup-progress",
        serde_json::json!({
            "stage": "Runtime installation complete. Verifying components…",
            "complete": true,
            "logPath": log_path.to_string_lossy()
        }),
    );
    Ok(format!(
        "Runtime setup completed. Log: {}",
        log_path.display()
    ))
}

fn chrono_free_timestamp() -> String {
    // Avoid another dependency; the log header is informational.
    format!("{:?}", std::time::SystemTime::now())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let root = installation::user_root().expect("Windows user directory unavailable");
    // A desktop-lifetime mutex also prevents an update while another shell's
    // backend is using the old payload. Windows releases it on forced exit.
    let _desktop = match installation::InstallationLock::acquire(&root, "Desktop", 0) {
        Ok(lock) => lock,
        Err(error) => {
            eprintln!("{error}");
            return;
        }
    };
    tauri::Builder::default()
        .manage(Mutex::new(Supervisor::default()))
        .manage(Mutex::new(SetupLifecycle::default()))
        .invoke_handler(tauri::generate_handler![
            start_services,
            prepare_update_install,
            restore_services_after_update_failure,
            stop_services,
            service_status,
            get_api_token,
            check_runtime,
            install_app_payload,
            setup_runtime,
            open_external_url,
            choose_data_directory,
            move_data_directory,
            reveal_library_path,
            begin_file_download,
            append_file_download_chunk,
            finish_file_download,
            cancel_file_download,
            reveal_file_download
        ])
        .build(tauri::generate_context!())
        .expect("error while building Clippy desktop application")
        .run(|app, event| {
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                if let Ok(mut setup) = app.state::<Mutex<SetupLifecycle>>().lock() {
                    setup.exiting = true;
                    setup.job.take();
                }
            }
        });
}
