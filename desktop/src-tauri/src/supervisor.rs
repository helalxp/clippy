use serde::Serialize;
use std::{
    env,
    fs::{self, File, OpenOptions},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8000;
const RENDERER_HOST: &str = "127.0.0.1";
const RENDERER_PORT: u16 = 13100;

#[derive(Default)]
pub struct Supervisor {
    backend: Option<Child>,
    renderer: Option<Child>,
    paths: Option<RuntimePaths>,
}

#[derive(Clone)]
struct RuntimePaths {
    root: PathBuf,
    python: PathBuf,
    node: PathBuf,
    ffmpeg: PathBuf,
    output: PathBuf,
    uploads: PathBuf,
    models: PathBuf,
    logs: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct ServiceStatus {
    pub backend: String,
    pub renderer: String,
    pub output_directory: String,
    pub setup_required: bool,
    pub message: String,
}

impl RuntimePaths {
    fn discover() -> Result<Self, String> {
        let local = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| "Windows LOCALAPPDATA directory is unavailable".to_string())?;
        let root = env::var_os("CLIPPY_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| local.join("Clippy"));
        let app = root.join("app").join("current");
        let runtime = root.join("runtime");
        let python = env::var_os("CLIPPY_PYTHON_EXE")
            .map(PathBuf::from)
            .unwrap_or_else(|| runtime.join("python").join("python.exe"));
        let node = env::var_os("CLIPPY_NODE_EXE")
            .map(PathBuf::from)
            .unwrap_or_else(|| runtime.join("node").join("node.exe"));
        let ffmpeg = runtime.join("ffmpeg").join("bin");
        let output = root.join("data").join("output");
        let uploads = root.join("data").join("uploads");
        let models = root.join("data").join("models");
        let logs = root.join("logs");
        Ok(Self { root: app, python, node, ffmpeg, output, uploads, models, logs })
    }

    fn validate(&self) -> Result<(), String> {
        let required = [
            (&self.python, "Managed Python runtime"),
            (&self.node, "Managed Node.js runtime"),
            (&self.ffmpeg.join("ffmpeg.exe"), "Managed FFmpeg runtime"),
            (&self.root.join("app.py"), "Clippy backend payload (app.py)"),
            (&self.root.join("render-service").join("dist").join("server.js"), "Compiled renderer"),
            (&self.root.join("remotion").join("src").join("index.ts"), "Remotion source"),
        ];
        let missing: Vec<String> = required.iter()
            .filter(|(path, _)| !path.is_file())
            .map(|(path, label)| format!("{}: {}", label, path.display()))
            .collect();
        if !missing.is_empty() {
            return Err(format!(
                "Clippy's first-run setup is not complete. Missing components:\n{}\nRun the dependency setup before starting services.",
                missing.join("\n")
            ));
        }
        Ok(())
    }
}

impl Supervisor {
    pub fn start(&mut self) -> Result<ServiceStatus, String> {
        if self.backend.is_some() || self.renderer.is_some() {
            let status = self.status()?;
            if status.backend == "running" && status.renderer == "running" {
                return Ok(status);
            }
            let _ = self.stop();
        }

        let paths = RuntimePaths::discover()?;
        paths.validate()?;
        fs::create_dir_all(&paths.output).map_err(|e| format!("Cannot create output directory: {e}"))?;
        fs::create_dir_all(&paths.uploads).map_err(|e| format!("Cannot create uploads directory: {e}"))?;
        fs::create_dir_all(&paths.models).map_err(|e| format!("Cannot create models directory: {e}"))?;
        fs::create_dir_all(&paths.logs).map_err(|e| format!("Cannot create log directory: {e}"))?;
        let mut child_path = vec![paths.ffmpeg.clone()];
        if let Some(existing) = env::var_os("PATH") {
            child_path.extend(env::split_paths(&existing));
        }
        let child_path = env::join_paths(child_path)
            .map_err(|e| format!("Cannot construct application PATH: {e}"))?;

        let backend_log = open_log(&paths.logs.join("backend.log"))?;
        let renderer_log = open_log(&paths.logs.join("renderer.log"))?;
        let renderer_stdout = renderer_log.try_clone().map_err(|e| e.to_string())?;
        let mut backend = Command::new(&paths.python)
            .args(["-m", "uvicorn", "app:app", "--host", BACKEND_HOST, "--port", "8000"])
            .current_dir(&paths.root)
            .env("PYTHONPATH", &paths.root)
            .env("OUTPUT_DIR", &paths.output)
            .env("UPLOAD_DIR", &paths.uploads)
            .env("HF_HOME", paths.models.join("huggingface"))
            .env("HUGGINGFACE_HUB_CACHE", paths.models.join("huggingface").join("hub"))
            .env("TORCH_HOME", paths.models.join("torch"))
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .env("CLIPPY_SETTINGS_PATH", env::var_os("LOCALAPPDATA").unwrap_or_default())
            .env("PATH", &child_path)
            .env("RENDER_SERVICE_URL", format!("http://{RENDERER_HOST}:{RENDERER_PORT}"))
            .env("HOST", BACKEND_HOST)
            .env("PORT", BACKEND_PORT.to_string())
            .stdout(Stdio::from(backend_log.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(backend_log))
            .spawn()
            .map_err(|e| format!("Could not start the Clippy backend: {e}"))?;

        let renderer = Command::new(&paths.node)
            .arg(paths.root.join("render-service").join("dist").join("server.js"))
            .current_dir(paths.root.join("render-service"))
            .env("HOST", RENDERER_HOST)
            .env("PORT", RENDERER_PORT.to_string())
            .env("OUTPUT_DIR", &paths.output)
            .env("PATH", &child_path)
            .env("REMOTION_BUNDLE_PATH", paths.root.join("remotion"))
            .stdout(Stdio::from(renderer_stdout))
            .stderr(Stdio::from(renderer_log))
            .spawn();

        let mut renderer = match renderer {
            Ok(child) => child,
            Err(error) => { let _ = backend.kill(); let _ = backend.wait(); return Err(format!("Could not start the Remotion renderer: {error}")); }
        };

        if let Err(error) = wait_for_health(&mut backend, BACKEND_PORT, "/health/ready", Duration::from_secs(90)) {
            let _ = renderer.kill(); let _ = renderer.wait();
            let _ = backend.kill(); let _ = backend.wait();
            return Err(format!("Backend startup failed: {error}. See {}", paths.logs.join("backend.log").display()));
        }
        if let Err(error) = wait_for_health(&mut renderer, RENDERER_PORT, "/health", Duration::from_secs(120)) {
            let _ = renderer.kill(); let _ = renderer.wait();
            let _ = backend.kill(); let _ = backend.wait();
            return Err(format!("Renderer startup failed: {error}. See {}", paths.logs.join("renderer.log").display()));
        }

        self.backend = Some(backend);
        self.renderer = Some(renderer);
        self.paths = Some(paths);
        self.status()
    }

    pub fn stop(&mut self) -> Result<ServiceStatus, String> {
        stop_child(&mut self.renderer);
        stop_child(&mut self.backend);
        self.status()
    }

    pub fn status(&mut self) -> Result<ServiceStatus, String> {
        let backend = child_status(&mut self.backend);
        let renderer = child_status(&mut self.renderer);
        let paths = self.paths.clone().or_else(|| RuntimePaths::discover().ok());
        let output_directory = paths.as_ref().map(|p| p.output.display().to_string()).unwrap_or_default();
        let setup_required = paths.as_ref().map(|p| p.validate().is_err()).unwrap_or(true);
        let message = if setup_required {
            "First-run dependency setup is required before Clippy can start.".to_string()
        } else if backend == "running" && renderer == "running" {
            "Clippy services are ready.".to_string()
        } else {
            "Clippy services are not running.".to_string()
        };
        Ok(ServiceStatus { backend, renderer, output_directory, setup_required, message })
    }
}

fn open_log(path: &Path) -> Result<File, String> {
    OpenOptions::new().create(true).append(true).open(path)
        .map_err(|e| format!("Cannot open log {}: {e}", path.display()))
}

fn wait_for_health(child: &mut Child, port: u16, path: &str, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            return Err(format!("service exited early with status {status}"));
        }
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            use std::io::{Read, Write};
            stream.set_read_timeout(Some(Duration::from_secs(2))).ok();
            let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok() && response.starts_with("HTTP/1.1 200") {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!("health endpoint {path} on 127.0.0.1:{port} did not become ready before timeout"))
}

fn child_status(child: &mut Option<Child>) -> String {
    match child {
        Some(process) => match process.try_wait() {
            Ok(None) => "running".to_string(),
            Ok(Some(status)) => format!("exited ({status})"),
            Err(error) => format!("unknown ({error})"),
        },
        None => "stopped".to_string(),
    }
}

fn stop_child(child: &mut Option<Child>) {
    if let Some(mut process) = child.take() {
        let _ = process.kill();
        let _ = process.wait();
    }
}
