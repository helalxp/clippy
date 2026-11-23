use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BootstrapConfig {
    pub runtime_root: PathBuf,
    pub manifest_path: PathBuf,
    pub data_root: PathBuf,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeComponent {
    pub version: String,
    pub installed: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeManifest {
    pub version: String,
    pub schema: u32,
    pub state: String,
    pub requirements_sha256: String,
    #[serde(default)]
    pub browser_sha256: Option<String>,
    pub components: HashMap<String, RuntimeComponent>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuInfo {
    pub vendor: String,
    pub renderer: String,
    pub vram_mb: Option<u64>,
    pub compute_api: Vec<String>,
}
#[derive(Debug, Clone, Serialize)]
pub struct BootstrapStatus {
    pub stage: String,
    pub progress: f32,
    pub message: String,
    pub error: Option<String>,
    pub gpu: Option<GpuInfo>,
}
pub struct Bootstrap {
    config: BootstrapConfig,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeContract {
    schema: u32,
    python: String,
    node: String,
    ffmpeg: String,
    browser_sha256: String,
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T, String> {
    let text =
        fs::read_to_string(path).map_err(|e| format!("Cannot read {}: {e}", path.display()))?;
    serde_json::from_str(text.trim_start_matches('\u{feff}'))
        .map_err(|e| format!("Invalid {}: {e}", path.display()))
}
fn parse_manifest_state(state: &str) -> Result<HashMap<String, String>, String> {
    let mut fields = HashMap::new();
    for segment in state.split(';') {
        let (key, value) = segment.split_once('=').ok_or("Malformed runtime state")?;
        let (key, value) = (key.trim(), value.trim());
        if key.is_empty() || value.is_empty() {
            return Err("Empty runtime state field".into());
        }
        if fields.insert(key.into(), value.into()).is_some() {
            return Err(format!("Duplicate runtime field '{key}'"));
        }
    }
    Ok(fields)
}
fn sha256(path: &Path) -> Result<String, String> {
    let mut file =
        fs::File::open(path).map_err(|e| format!("Cannot read {}: {e}", path.display()))?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hash.finalize()))
}
fn validate_contract(manifest: &RuntimeManifest, app: &Path) -> Result<(), String> {
    let contract: RuntimeContract = read_json(&app.join("runtime-contract.json"))?;
    if contract.schema != 1 || manifest.version != "1.0.0" || manifest.schema != 1 {
        return Err("Unsupported runtime manifest/contract schema".into());
    }
    let renderer: serde_json::Value =
        read_json(&app.join("render-service/node_modules/@remotion/renderer/package.json"))?;
    let browser = renderer["version"]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or("Bundled renderer version missing")?;
    let state = parse_manifest_state(&manifest.state)?;
    for (name, expected) in [
        ("python", contract.python.as_str()),
        ("node", contract.node.as_str()),
        ("ffmpeg", contract.ffmpeg.as_str()),
        ("browser", browser),
    ] {
        let component = manifest
            .components
            .get(name)
            .ok_or_else(|| format!("Runtime manifest missing {name}"))?;
        if !component.installed || component.version != expected {
            return Err(format!(
                "Managed {name} version mismatch: expected {expected}, found {}",
                component.version
            ));
        }
        if state.get(name).map(String::as_str) != Some(expected) {
            return Err(format!(
                "Runtime state field '{name}' does not match payload"
            ));
        }
    }
    if !matches!(
        state.get("pythonVariant").map(String::as_str),
        Some("cpu" | "cuda")
    ) {
        return Err("Invalid Python runtime variant".into());
    }
    let requirements = sha256(&app.join("requirements.txt"))?;
    if requirements != manifest.requirements_sha256.to_ascii_lowercase()
        || state.get("requirements") != Some(&requirements)
    {
        return Err("Runtime requirements do not match installed payload".into());
    }
    Ok(())
}

// Read both pipes concurrently. A timeout kills descendants as well as the
// probe, so checking a broken runtime cannot strand a browser or block Retry.
fn checked_output(command: &mut Command, timeout: Duration) -> Result<String, String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let job = super::supervisor::ProcessJob::new()?;
    let mut child = command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    if let Err(error) = job.assign(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    let stdout = child.stdout.take().ok_or("Missing process stdout")?;
    let stderr = child.stderr.take().ok_or("Missing process stderr")?;
    fn drain(mut pipe: impl Read) -> String {
        let mut saved = Vec::new();
        let mut buffer = [0u8; 4096];
        while let Ok(count) = pipe.read(&mut buffer) {
            if count == 0 {
                break;
            }
            let keep = count.min(65536usize.saturating_sub(saved.len()));
            saved.extend_from_slice(&buffer[..keep]);
        }
        String::from_utf8_lossy(&saved).into_owned()
    }
    let out = thread::spawn(move || drain(stdout));
    let err = thread::spawn(move || drain(stderr));
    let deadline = Instant::now() + timeout;
    let result = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Err(error) => break Err(error.to_string()),
            Ok(None) if Instant::now() >= deadline => break Err("Runtime check timed out".into()),
            _ => thread::sleep(Duration::from_millis(50)),
        }
    };
    drop(job);
    if result.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    let stdout = out.join().unwrap_or_default();
    let stderr = err.join().unwrap_or_default();
    let status = result?;
    if !status.success() {
        return Err(format!("Runtime check exited {status}: {stderr}"));
    }
    Ok(if stdout.trim().is_empty() {
        stderr
    } else {
        stdout
    })
}

impl Bootstrap {
    pub fn new(config: BootstrapConfig) -> Self {
        Self { config }
    }
    fn root(&self) -> &Path {
        self.config
            .manifest_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
    }
    fn command(&self, exe: &Path) -> Command {
        let mut command = Command::new(exe);
        for key in [
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONUSERBASE",
            "PYTHONSTARTUP",
            "PYTHONEXECUTABLE",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "CONDA_EXE",
            "NODE_OPTIONS",
            "NODE_PATH",
        ] {
            command.env_remove(key);
        }
        let root = self.root();
        let python = self.config.runtime_root.join("python");
        let mut paths = vec![
            python.clone(),
            python.join("Lib/site-packages/torch/lib"),
            self.config.runtime_root.join("node"),
            self.config.runtime_root.join("ffmpeg/bin"),
        ];
        if let Some(system) = std::env::var_os("SystemRoot") {
            paths.push(PathBuf::from(system).join("System32"));
        }
        if let Ok(path) = std::env::join_paths(paths) {
            command.env("PATH", path);
        }
        command
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUTF8", "1")
            .env("CLIPPY_DATA_DIR", &self.config.data_root)
            .env("OUTPUT_DIR", self.config.data_root.join("output"))
            .env("UPLOAD_DIR", self.config.data_root.join("uploads"))
            .env("CLIPPY_LIBRARY_DIR", self.config.data_root.join("library"))
            .env(
                "REFERENCE_TEMPLATES_DIR",
                self.config.data_root.join("reference_templates"),
            )
            .env("CLIPPY_SETTINGS_PATH", root.join("settings.json"))
            .env("CLIPPY_MODELS_DIR", self.config.data_root.join("models"))
            .env("HF_HOME", self.config.data_root.join("models/huggingface"))
            .env("TORCH_HOME", self.config.data_root.join("models/torch"))
            .env("HF_HUB_OFFLINE", "1");
        command
    }
    pub fn validate_components(&self) -> Vec<String> {
        let mut issues = Vec::new();
        for (relative, label, arg) in [
            ("python/python.exe", "Python runtime", "--version"),
            ("node/node.exe", "Node.js runtime", "--version"),
            ("ffmpeg/bin/ffmpeg.exe", "FFmpeg runtime", "-version"),
            ("ffmpeg/bin/ffprobe.exe", "FFprobe runtime", "-version"),
        ] {
            let exe = self.config.runtime_root.join(relative);
            if let Err(error) = checked_output(self.command(&exe).arg(arg), Duration::from_secs(15))
            {
                issues.push(format!("{label} must be repaired: {error}"));
            }
        }
        issues
    }
    pub fn get_status(&self) -> Result<BootstrapStatus, String> {
        let mut issues = self.validate_components();
        let app = self.root().join("app/current");
        let validation = (|| {
            let manifest: RuntimeManifest = read_json(&self.config.manifest_path)?;
            validate_contract(&manifest, &app)?;
            for (component, relative, prefix) in [
                ("python", "python/python.exe", "Python "),
                ("node", "node/node.exe", "v"),
            ] {
                let output = checked_output(
                    self.command(&self.config.runtime_root.join(relative))
                        .arg("--version"),
                    Duration::from_secs(15),
                )?;
                if output.trim() != format!("{prefix}{}", manifest.components[component].version) {
                    return Err(format!("Managed {component} executable version mismatch"));
                }
            }
            let browser = self
                .root()
                .join("browser/headless-shell/chrome-headless-shell.exe");
            let contract: RuntimeContract = read_json(&app.join("runtime-contract.json"))?;
            let browser_actual = sha256(&browser)?;
            if browser_actual != contract.browser_sha256
                || Some(browser_actual) != manifest.browser_sha256.map(|v| v.to_ascii_lowercase())
            {
                return Err("Persistent browser hash mismatch".into());
            }
            let python = self.config.runtime_root.join("python/python.exe");
            // Detect outdated managed Python archives before the UI decides
            // whether setup/repair is needed. The PowerShell setup script has
            // the same checks and will install the runtime produced by this app
            // release when an older HTTP/script plugin layout is found.
            let script = r#"import sys,pathlib,app,torch,faster_whisper,ctranslate2,importlib.util; from yt_dlp_plugins.extractor.getpot_bgutil_http import BgUtilHTTPPTP; assert pathlib.Path(app.__file__).resolve() == (pathlib.Path(sys.argv[1])/'app.py').resolve(), 'Backend import escaped installed payload'; assert importlib.util.find_spec('yt_dlp_plugins.extractor.getpot_bgutil_script') is None, 'Legacy timeout-prone bgutil script provider is still installed'; assert not BgUtilHTTPPTP(None, None, {}).is_available(), 'bgutil HTTP provider must require an explicit managed base URL'; assert BgUtilHTTPPTP(None, None, {'base_url': ['http://127.0.0.1:4416']}).is_available(), 'bgutil HTTP provider must accept an explicit base URL'"#;
            checked_output(
                self.command(&python)
                    .current_dir(&app)
                    .args(["-c", script])
                    .arg(&app),
                Duration::from_secs(120),
            )
            .map_err(|e| format!("Backend dependencies need repair: {e}"))?;
            checked_output(
                self.command(&browser).args([
                    "--headless",
                    "--disable-gpu",
                    "--dump-dom",
                    "about:blank",
                ]),
                Duration::from_secs(30),
            )
            .map_err(|e| format!("Browser dependencies need repair: {e}"))?;
            Ok::<_, String>(())
        })();
        if let Err(error) = validation {
            issues.push(error);
        }
        let error = if issues.is_empty() {
            None
        } else {
            Some(issues.join("; "))
        };
        Ok(BootstrapStatus {
            stage: "validation".into(),
            progress: if error.is_none() { 100.0 } else { 0.0 },
            message: error
                .as_ref()
                .map(|e| format!("Runtime validation needs attention: {e}"))
                .unwrap_or_else(|| "Runtime components and dependencies are valid.".into()),
            error,
            gpu: self.detect_gpu_status(),
        })
    }
    fn detect_gpu_status(&self) -> Option<GpuInfo> {
        let output = checked_output(
            Command::new("nvidia-smi").args([
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ]),
            Duration::from_secs(5),
        )
        .ok()?;
        let parts: Vec<_> = output.lines().next()?.split(',').map(str::trim).collect();
        if parts.len() < 3 {
            return None;
        }
        Some(GpuInfo {
            vendor: "nvidia".into(),
            renderer: parts[0].into(),
            vram_mb: parts[1].parse().ok(),
            compute_api: vec!["cuda".into()],
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp_root() -> PathBuf {
        std::env::temp_dir().join(format!(
            "clippy-bootstrap-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }
    #[test]
    fn manifest_state_contract() {
        for fixture in [
            include_str!("../../tests/fixtures/runtime-manifest-state.txt"),
            include_str!("../../tests/fixtures/runtime-manifest-state-cuda.txt"),
        ] {
            assert_eq!(
                parse_manifest_state(fixture.trim()).unwrap()["python"],
                "3.12.10"
            );
        }
        for invalid in ["python=x;python=y", "python=", "broken"] {
            assert!(parse_manifest_state(invalid).is_err());
        }
    }
    #[test]
    fn payload_changes_invalidate_self_consistent_old_manifest() {
        let root = temp_root();
        let renderer = root.join("render-service/node_modules/@remotion/renderer");
        fs::create_dir_all(&renderer).unwrap();
        fs::write(
            root.join("runtime-contract.json"),
            include_str!("../../runtime-contract.json"),
        )
        .unwrap();
        fs::write(renderer.join("package.json"), r#"{"version":"4.0.447"}"#).unwrap();
        fs::write(root.join("requirements.txt"), b"requirements").unwrap();
        let hash = sha256(&root.join("requirements.txt")).unwrap();
        let mut manifest: RuntimeManifest = serde_json::from_value(serde_json::json!({
            "version":"1.0.0", "schema":1, "requirementsSha256":hash,
            "state":format!("python=3.12.10;pythonVariant=cpu;node=22.23.3;ffmpeg=9.1;browser=4.0.447;requirements={hash}"),
            "components":{"python":{"version":"3.12.10","installed":true},"node":{"version":"22.23.3","installed":true},"ffmpeg":{"version":"9.1","installed":true},"browser":{"version":"4.0.447","installed":true}}
        })).unwrap();
        validate_contract(&manifest, &root).unwrap();
        fs::write(renderer.join("package.json"), r#"{"version":"4.0.448"}"#).unwrap();
        assert!(validate_contract(&manifest, &root)
            .unwrap_err()
            .contains("browser version mismatch"));
        fs::write(renderer.join("package.json"), r#"{"version":"4.0.447"}"#).unwrap();
        manifest.components.get_mut("python").unwrap().version = "3.11.9".into();
        manifest.state = manifest.state.replace("3.12.10", "3.11.9");
        assert!(validate_contract(&manifest, &root)
            .unwrap_err()
            .contains("python version mismatch"));
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn damaged_executables_are_repairable() {
        let root = temp_root();
        for relative in [
            "python/python.exe",
            "node/node.exe",
            "ffmpeg/bin/ffmpeg.exe",
            "ffmpeg/bin/ffprobe.exe",
        ] {
            let path = root.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, b"broken executable").unwrap();
        }
        let bootstrap = Bootstrap::new(BootstrapConfig {
            runtime_root: root.clone(),
            manifest_path: root.join("runtime-manifest.json"),
            data_root: root.join("data"),
        });
        assert_eq!(bootstrap.validate_components().len(), 4);
        assert!(bootstrap.get_status().unwrap().error.is_some());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn runtime_validation_commands_use_the_configured_data_location() {
        use std::ffi::OsStr;

        let root = temp_root();
        fs::create_dir_all(&root).unwrap();
        let data_root = root.join("external-data");
        let bootstrap = Bootstrap::new(BootstrapConfig {
            runtime_root: root.join("runtime"),
            manifest_path: root.join("runtime-manifest.json"),
            data_root: data_root.clone(),
        });
        let command = bootstrap.command(Path::new("python.exe"));
        let env_value = |name: &str| {
            command
                .get_envs()
                .find(|(key, _)| *key == OsStr::new(name))
                .and_then(|(_, value)| value)
                .map(|value| value.to_os_string())
        };
        assert_eq!(env_value("CLIPPY_DATA_DIR"), Some(data_root.clone().into_os_string()));
        assert_eq!(env_value("OUTPUT_DIR"), Some(data_root.join("output").into_os_string()));
        assert_eq!(env_value("UPLOAD_DIR"), Some(data_root.join("uploads").into_os_string()));
        assert_eq!(env_value("CLIPPY_LIBRARY_DIR"), Some(data_root.join("library").into_os_string()));
        assert_eq!(env_value("CLIPPY_MODELS_DIR"), Some(data_root.join("models").into_os_string()));
        assert_eq!(
            env_value("REFERENCE_TEMPLATES_DIR"),
            Some(data_root.join("reference_templates").into_os_string())
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    #[cfg(windows)]
    fn functional_checks_fail_on_error_and_timeout() {
        let shell = PathBuf::from(std::env::var_os("SystemRoot").unwrap())
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        assert!(checked_output(
            Command::new(&shell).args(["-NoProfile", "-Command", "exit 1"]),
            Duration::from_secs(10)
        )
        .is_err());
        assert!(checked_output(
            Command::new(&shell).args(["-NoProfile", "-Command", "Start-Sleep -Seconds 30"]),
            Duration::from_millis(200)
        )
        .unwrap_err()
        .contains("timed out"));
    }
}
