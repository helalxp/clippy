use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BootstrapConfig {
    pub runtime_root: PathBuf,
    pub manifest_path: PathBuf,
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
    pub components: std::collections::HashMap<String, RuntimeComponent>,
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

/// Parse the PowerShell-generated manifest state without relying on key order.
/// Unknown keys are tolerated for forward-compatible optional metadata, while
/// duplicate, empty, or malformed keys are rejected.
fn parse_manifest_state(state: &str) -> Result<std::collections::HashMap<String, String>, String> {
    let mut fields = std::collections::HashMap::new();
    for segment in state.split(';') {
        let (key, value) = segment.split_once('=')
            .ok_or_else(|| "Runtime manifest state contains a malformed field".to_string())?;
        let key = key.trim();
        let value = value.trim();
        if key.is_empty() || value.is_empty() {
            return Err("Runtime manifest state contains an empty key or value".to_string());
        }
        if fields.insert(key.to_string(), value.to_string()).is_some() {
            return Err(format!("Runtime manifest state contains duplicate field '{key}'"));
        }
    }
    Ok(fields)
}

impl Bootstrap {
    pub fn new(config: BootstrapConfig) -> Self {
        Self { config }
    }

    pub fn verify_installation(&self) -> Result<bool, String> {
        let python_exe = self.config.runtime_root.join("python").join("python.exe");
        let node_exe = self.config.runtime_root.join("node").join("node.exe");
        let ffmpeg_exe = self
            .config
            .runtime_root
            .join("ffmpeg")
            .join("bin")
            .join("ffmpeg.exe");

        Ok(python_exe.exists() && node_exe.exists() && ffmpeg_exe.exists())
    }

    pub fn validate_components(&self) -> Result<Vec<String>, String> {
        let mut missing = Vec::new();
        let python_exe = self.config.runtime_root.join("python").join("python.exe");
        let node_exe = self.config.runtime_root.join("node").join("node.exe");
        let ffmpeg_exe = self
            .config
            .runtime_root
            .join("ffmpeg")
            .join("bin")
            .join("ffmpeg.exe");

        if !python_exe.exists() {
            missing.push("Python runtime not found".to_string());
        } else {
            Self::test_executable(&python_exe, &["--version"])?;
        }

        if !node_exe.exists() {
            missing.push("Node.js runtime not found".to_string());
        } else {
            Self::test_executable(&node_exe, &["--version"])?;
        }

        if !ffmpeg_exe.exists() {
            missing.push("FFmpeg not found".to_string());
        } else {
            Self::test_executable(&ffmpeg_exe, &["-version"])?;
        }

        Ok(missing)
    }

    fn test_executable(exe: &Path, args: &[&str]) -> Result<(), String> {
        let output = Command::new(exe)
            .args(args)
            .output()
            .map_err(|e| format!("Cannot execute {}: {e}", exe.display()))?;

        if output.status.success() {
            Ok(())
        } else {
            Err(format!(
                "Executable test failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ))
        }
    }

    pub fn get_status(&self) -> Result<BootstrapStatus, String> {
        let mut issues = self.validate_components()?;
        let manifest_path = &self.config.manifest_path;
        let app_root = manifest_path.parent().unwrap_or_else(|| Path::new(".")).join("app").join("current");
        let requirements_path = app_root.join("requirements.txt");

        let manifest_result = fs::read_to_string(manifest_path)
            .map_err(|e| format!("Cannot read runtime manifest at {}: {e}", manifest_path.display()))
            .and_then(|content| {
                let json = content.trim_start_matches('\u{feff}');
                serde_json::from_str::<RuntimeManifest>(json)
                    .map_err(|e| format!("Runtime manifest JSON is malformed: {e}"))
            })
            .and_then(|manifest| {
                if manifest.version != "1.0.0" || manifest.schema != 1 {
                    return Err(format!("Unsupported runtime manifest version/schema: {}/{}", manifest.version, manifest.schema));
                }
                for name in ["python", "node", "ffmpeg"] {
                    let component = manifest.components.get(name)
                        .ok_or_else(|| format!("Runtime manifest is missing component '{name}'"))?;
                    if !component.installed || component.version.trim().is_empty() {
                        return Err(format!("Runtime manifest component '{name}' is not marked installed"));
                    }
                }
                let requirements = fs::read(&requirements_path)
                    .map_err(|e| format!("Cannot read bundled requirements at {}: {e}", requirements_path.display()))?;
                use sha2::{Digest, Sha256};
                let actual = format!("{:x}", Sha256::digest(&requirements));
                if actual != manifest.requirements_sha256.to_ascii_lowercase() {
                    return Err("Runtime manifest requirements hash does not match the installed application payload".to_string());
                }
                // The setup engine writes a key/value state string. Treat it as
                // structured metadata rather than comparing a reconstructed string:
                // PowerShell also records pythonVariant (cpu/cuda), and future
                // components may add keys without invalidating older validators.
                let state = parse_manifest_state(&manifest.state)?;
                let expected = [
                    ("python", manifest.components["python"].version.as_str()),
                    ("node", manifest.components["node"].version.as_str()),
                    ("ffmpeg", manifest.components["ffmpeg"].version.as_str()),
                    ("requirements", actual.as_str()),
                ];
                for (key, value) in expected {
                    match state.get(key) {
                        Some(actual_value) if actual_value == value => {}
                        Some(_) => return Err(format!(
                            "Runtime manifest state field '{key}' does not match its component or payload"
                        )),
                        None => return Err(format!(
                            "Runtime manifest state is missing required field '{key}'"
                        )),
                    }
                }
                if let Some(variant) = state.get("pythonVariant") {
                    if variant != "cpu" && variant != "cuda" {
                        return Err(format!("Unsupported Python runtime variant '{variant}'"));
                    }
                }
                Ok(())
            });

        if let Err(error) = manifest_result {
            issues.push(error);
        }

        let gpu_info = self.detect_gpu_status();
        let progress = if issues.is_empty() { 100.0 } else { 0.0 };
        Ok(BootstrapStatus {
            stage: "validation".to_string(),
            progress,
            message: if issues.is_empty() {
                "All runtime components and the runtime manifest are valid.".to_string()
            } else {
                format!("Runtime validation needs attention: {}", issues.join("; "))
            },
            error: if issues.is_empty() { None } else { Some(issues.join("; ")) },
            gpu: gpu_info,
        })
    }

    fn detect_gpu_status(&self) -> Option<GpuInfo> {
        // Run nvidia-smi to get GPU info
        let output = Command::new("nvidia-smi")
            .arg("--query-gpu=name,memory.total,driver.version")
            .output();

        // Handle both Ok and Err exhaustively
        if let Ok(result) = output {
            if result.status.success() {
                let stdout = String::from_utf8_lossy(&result.stdout);
                let lines: Vec<&str> = stdout.lines().collect();
                if let Some(first_line) = lines.first() {
                    let parts: Vec<&str> = first_line.split(',').map(|s| s.trim()).collect();
                    if parts.len() >= 3 {
                        let vendor = if parts[0].contains("NVIDIA") {
                            "nvidia"
                        } else if parts[0].contains("AMD") {
                            "amd"
                        } else if parts[0].contains("Intel") {
                            "intel"
                        } else {
                            "unknown"
                        };
                        let renderer = parts[0].to_string();
                        let vram_mb: Option<u64> = parts[1].replace(" MiB", "").parse().ok();

                        return Some(GpuInfo {
                            vendor: vendor.to_string(),
                            renderer,
                            vram_mb,
                            compute_api: vec!["cuda".to_string()],
                        });
                    }
                }
            }
        }

        // No NVIDIA GPU or nvidia-smi failed
        None
    }

    pub fn install_from_archive(
        &self,
        archive: &Path,
        component_name: &str,
    ) -> Result<(), String> {
        let extract_dir = self
            .config
            .runtime_root
            .join(component_name);

        fs::create_dir_all(&extract_dir)
            .map_err(|e| format!("Cannot create directory: {e}"))?;

        let file = std::fs::File::open(archive)
            .map_err(|e| format!("Cannot open archive: {e}"))?;
        let mut zip = zip::ZipArchive::new(file)
            .map_err(|e| format!("Invalid zip archive: {e}"))?;

        zip.extract(&extract_dir)
            .map_err(|e| format!("Cannot extract archive: {e}"))?;

        Ok(())
    }

    pub fn register_environment(&self) -> Result<(), String> {
        let python_exe = self.config.runtime_root.join("python").join("python.exe");
        let node_exe = self.config.runtime_root.join("node").join("node.exe");

        // On Windows, set environment variables via registry
        #[cfg(target_os = "windows")]
        {
            use std::env;
            // Set as process env vars for now; registry updates require elevated privileges
            env::set_var("CLIPPY_PYTHON_EXE", python_exe.to_string_lossy().to_string());
            env::set_var("CLIPPY_NODE_EXE", node_exe.to_string_lossy().to_string());
        }

        #[cfg(not(target_os = "windows"))]
        {
            use std::env;
            env::set_var("CLIPPY_PYTHON_EXE", python_exe.to_string_lossy().to_string());
            env::set_var("CLIPPY_NODE_EXE", node_exe.to_string_lossy().to_string());
        }

        Ok(())
    }
}

#[cfg(test)]
mod manifest_state_tests {
    use super::parse_manifest_state;

    #[test]
    fn accepts_power_shell_generated_cpu_manifest_state() {
        let parsed = parse_manifest_state(
            "python=3.12.10;pythonVariant=cpu;node=22.23.3;ffmpeg=gyan-release-essentials;requirements=0123456789abcdef"
        ).unwrap();
        assert_eq!(parsed.get("python").unwrap(), "3.12.10");
        assert_eq!(parsed.get("pythonVariant").unwrap(), "cpu");
        assert_eq!(parsed.get("node").unwrap(), "22.23.3");
        assert_eq!(parsed.get("ffmpeg").unwrap(), "gyan-release-essentials");
        assert_eq!(parsed.get("requirements").unwrap(), "0123456789abcdef");
    }

    #[test]
    fn accepts_power_shell_generated_cuda_manifest_state() {
        let parsed = parse_manifest_state(
            "python=3.12.10;pythonVariant=cuda;node=22.23.3;ffmpeg=gyan-release-essentials;requirements=0123456789abcdef"
        ).unwrap();
        assert_eq!(parsed.get("pythonVariant").unwrap(), "cuda");
    }

    #[test]
    fn rejects_duplicate_or_malformed_fields() {
        assert!(parse_manifest_state("python=3.12;python=3.13").is_err());
        assert!(parse_manifest_state("python=3.12;broken").is_err());
        assert!(parse_manifest_state("python=").is_err());
    }
}
