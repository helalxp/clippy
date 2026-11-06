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
pub struct RuntimeManifest {
    pub version: String,
    pub components: std::collections::HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BootstrapStatus {
    pub stage: String,
    pub progress: f32,
    pub message: String,
    pub error: Option<String>,
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
        let missing = self.validate_components()?;
        let progress = if missing.is_empty() { 100.0 } else { 0.0 };

        Ok(BootstrapStatus {
            stage: "validation".to_string(),
            progress,
            message: if missing.is_empty() {
                "All runtime components are installed and functional.".to_string()
            } else {
                format!("Missing components: {}", missing.join(", "))
            },
            error: if missing.is_empty() {
                None
            } else {
                Some(missing.join("; "))
            },
        })
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
