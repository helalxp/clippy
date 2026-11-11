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
                let expected_state = format!(
                    "python={};node={};ffmpeg={};requirements={}",
                    manifest.components["python"].version,
                    manifest.components["node"].version,
                    manifest.components["ffmpeg"].version,
                    actual
                );
                if manifest.state != expected_state {
                    return Err("Runtime manifest state does not match its component versions and requirements hash".to_string());
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