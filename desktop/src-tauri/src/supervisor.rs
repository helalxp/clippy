use serde::Serialize;
use std::{
    env,
    fs::{self, File, OpenOptions},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

// Values belonging to the inherited hosted service must never enter the
// desktop backend or renderer process. Keep this list aligned with
// clippy_runtime_mode.HOSTED_ENV_DENYLIST.
const HOSTED_ENV_DENYLIST: &[&str] = &[
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "REDIS_URL",
    "JWT_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "EMAIL_FROM",
    "ADMIN_EMAIL",
    "REVIEW_LOGIN_EMAIL",
    "REVIEW_LOGIN_PASSWORD",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "OPENAI_APPS_CHALLENGE",
    "FRONTEND_URL",
    "PUBLIC_API_URL",
    "ALLOWED_ORIGINS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "AGENTLEDGER_API_URL",
    "AGENTLEDGER_API_KEY",
    "AGENTLEDGER_TREASURY_ID",
    "MANAGED_GEMINI_API_KEY",
    "MANAGED_UPLOAD_POST_API_KEY",
    "OPENSHORTS_LOGO_URL",
    "R2_ENDPOINT",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_PUBLIC_BASE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_S3_BUCKET",
    "AWS_S3_PUBLIC_BUCKET",
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_S3",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENPANEL_CLIENT_SECRET",
];

fn apply_local_only_environment(command: &mut Command) {
    command
        .env("CLIPPY_DESKTOP_MODE", "1")
        .env("BILLING_ENABLED", "0");
    for name in HOSTED_ENV_DENYLIST {
        command.env_remove(*name);
    }
}

// Keep the backend, renderer, and every descendant in one Windows Job
// Object. Windows closes the job handle when Clippy is force-terminated; the
// KILL_ON_JOB_CLOSE limit then reaps uvicorn workers, ffmpeg, Chromium, and
// other grandchildren even when Rust Drop cannot run.
#[cfg(windows)]
pub(crate) struct ProcessJob {
    // Store the opaque HANDLE as an integer so Supervisor remains Send + Sync
    // when managed by Tauri's thread-safe state container.
    handle: usize,
}

#[cfg(windows)]
impl ProcessJob {
    pub(crate) fn new() -> Result<Self, String> {
        use std::{mem, ptr};
        const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: u32 = 9;
        const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x0000_2000;

        #[repr(C)]
        #[derive(Clone, Copy)]
        struct BasicLimitInformation {
            per_process_user_time_limit: i64,
            per_job_user_time_limit: i64,
            limit_flags: u32,
            minimum_working_set_size: usize,
            maximum_working_set_size: usize,
            active_process_limit: u32,
            affinity: usize,
            priority_class: u32,
            scheduling_class: u32,
        }
        #[repr(C)]
        #[derive(Clone, Copy)]
        struct IoCounters {
            read_operation_count: u64,
            write_operation_count: u64,
            other_operation_count: u64,
            read_transfer_count: u64,
            write_transfer_count: u64,
            other_transfer_count: u64,
        }
        #[repr(C)]
        struct ExtendedLimitInformation {
            basic_limit_information: BasicLimitInformation,
            io_info: IoCounters,
            process_memory_limit: usize,
            job_memory_limit: usize,
            peak_process_memory_used: usize,
            peak_job_memory_used: usize,
        }
        #[link(name = "kernel32")]
        extern "system" {
            fn CreateJobObjectW(
                attributes: *const std::ffi::c_void,
                name: *const u16,
            ) -> *mut std::ffi::c_void;
            fn SetInformationJobObject(
                job: *mut std::ffi::c_void,
                class: u32,
                info: *const std::ffi::c_void,
                length: u32,
            ) -> i32;
            fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
        }

        unsafe {
            let handle = CreateJobObjectW(ptr::null(), ptr::null());
            if handle.is_null() {
                return Err(format!(
                    "Could not create the Clippy process job (Windows error {}).",
                    std::io::Error::last_os_error()
                ));
            }
            let mut info: ExtendedLimitInformation = mem::zeroed();
            info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = SetInformationJobObject(
                handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                &info as *const _ as *const std::ffi::c_void,
                mem::size_of::<ExtendedLimitInformation>() as u32,
            );
            if configured == 0 {
                let error = std::io::Error::last_os_error();
                CloseHandle(handle);
                return Err(format!(
                    "Could not configure Clippy process cleanup: {error}"
                ));
            }
            Ok(Self {
                handle: handle as usize,
            })
        }
    }

    pub(crate) fn assign(&self, child: &Child) -> Result<(), String> {
        const PROCESS_TERMINATE: u32 = 0x0001;
        const PROCESS_SET_QUOTA: u32 = 0x0100;
        #[link(name = "kernel32")]
        extern "system" {
            fn OpenProcess(access: u32, inherit: i32, process_id: u32) -> *mut std::ffi::c_void;
            fn AssignProcessToJobObject(
                job: *mut std::ffi::c_void,
                process: *mut std::ffi::c_void,
            ) -> i32;
            fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
        }
        unsafe {
            let process = OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA, 0, child.id());
            if process.is_null() {
                return Err(format!(
                    "Could not open service process {} for job assignment: {}",
                    child.id(),
                    std::io::Error::last_os_error()
                ));
            }
            let assigned = AssignProcessToJobObject(self.handle as *mut std::ffi::c_void, process);
            let error = if assigned == 0 {
                Some(std::io::Error::last_os_error())
            } else {
                None
            };
            CloseHandle(process);
            if let Some(error) = error {
                return Err(format!(
                    "Could not attach service process {} to the Clippy cleanup job: {error}",
                    child.id()
                ));
            }
            Ok(())
        }
    }
}

#[cfg(windows)]
impl Drop for ProcessJob {
    fn drop(&mut self) {
        #[link(name = "kernel32")]
        extern "system" {
            fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
        }
        unsafe {
            CloseHandle(self.handle as *mut std::ffi::c_void);
        }
    }
}

#[cfg(not(windows))]
pub(crate) struct ProcessJob;

#[cfg(not(windows))]
impl ProcessJob {
    pub(crate) fn new() -> Result<Self, String> {
        Ok(Self)
    }
    pub(crate) fn assign(&self, _child: &Child) -> Result<(), String> {
        Ok(())
    }
}

#[cfg(windows)]
fn generate_api_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    const BCRYPT_USE_SYSTEM_PREFERRED_RNG: u32 = 0x0000_0002;
    #[link(name = "bcrypt")]
    extern "system" {
        fn BCryptGenRandom(
            algorithm: *mut std::ffi::c_void,
            buffer: *mut u8,
            length: u32,
            flags: u32,
        ) -> i32;
    }
    let status = unsafe {
        BCryptGenRandom(
            std::ptr::null_mut(),
            bytes.as_mut_ptr(),
            bytes.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    if status < 0 {
        return Err(format!(
            "Windows could not generate a private local API token (NTSTATUS 0x{:08X}).",
            status as u32
        ));
    }
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

#[cfg(not(windows))]
fn generate_api_token() -> Result<String, String> {
    use std::hash::{BuildHasher, Hasher};
    let mut output = String::new();
    for _ in 0..4 {
        let state = std::collections::hash_map::RandomState::new();
        let mut hasher = state.build_hasher();
        hasher.write_u128(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos(),
        );
        hasher.write_u32(std::process::id());
        output.push_str(&format!("{:016x}", hasher.finish()));
    }
    Ok(output)
}

const BACKEND_HOST: &str = "127.0.0.1";
const RENDERER_HOST: &str = "127.0.0.1";

fn allocate_loopback_port() -> Result<u16, String> {
    // Ask Windows for an available ephemeral port instead of assuming that
    // fixed ports belong to Clippy. The listener is released immediately
    // before the child binds; startup health checks catch the rare race.
    let listener = TcpListener::bind((BACKEND_HOST, 0))
        .map_err(|e| format!("Could not reserve a local service port: {e}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|e| format!("Could not inspect the reserved local service port: {e}"))
}

#[derive(Default)]
pub struct Supervisor {
    backend: Option<Child>,
    renderer: Option<Child>,
    paths: Option<RuntimePaths>,
    job: Option<ProcessJob>,
    backend_port: u16,
    renderer_port: u16,
    api_token: Option<String>,
}

#[derive(Clone)]
struct RuntimePaths {
    root: PathBuf,
    python: PathBuf,
    node: PathBuf,
    ffmpeg: PathBuf,
    bgutil_script: PathBuf,
    browser_executable: PathBuf,
    data_root: PathBuf,
    output: PathBuf,
    uploads: PathBuf,
    library: PathBuf,
    models: PathBuf,
    settings_file: PathBuf,
    references: PathBuf,
    logs: PathBuf,
}

#[derive(Debug, Serialize)]
pub struct ServiceStatus {
    pub backend: String,
    pub renderer: String,
    pub backend_url: String,
    pub renderer_url: String,
    pub output_directory: String,
    pub setup_required: bool,
    pub message: String,
}

impl RuntimePaths {
    fn discover() -> Result<Self, String> {
        let local = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .ok_or_else(|| "Windows LOCALAPPDATA directory is unavailable".to_string())?;
        // All installer, runtime-check, and setup paths are anchored to
        // %LOCALAPPDATA%\\Clippy. Do not let a stray CLIPPY_HOME environment
        // variable make the supervisor launch from a different installation.
        let root = local.join("Clippy");
        let app = root.join("app").join("current");
        let runtime = root.join("runtime");
        let data_root = crate::data_storage::configured_data_directory(&root)?;
        // These executable paths are owned by the installation. Do not let
        // ambient environment overrides redirect Clippy to system Python/Node.
        let python = runtime.join("python").join("python.exe");
        let node = runtime.join("node").join("node.exe");
        let ffmpeg = runtime.join("ffmpeg").join("bin");
        let bgutil_script = app
            .join("bgutil-provider")
            .join("server")
            .join("build")
            .join("generate_once.js");
        let browser_executable = root
            .join("browser")
            .join("headless-shell")
            .join("chrome-headless-shell.exe");
        let output = data_root.join("output");
        let uploads = data_root.join("uploads");
        let library = data_root.join("library");
        let models = data_root.join("models");
        let settings_file = root.join("settings.json");
        let references = data_root.join("reference_templates");
        let logs = root.join("logs");
        Ok(Self {
            root: app,
            python,
            node,
            ffmpeg,
            bgutil_script,
            browser_executable,
            data_root,
            output,
            uploads,
            library,
            models,
            settings_file,
            references,
            logs,
        })
    }

    fn validate(&self) -> Result<(), String> {
        let required = [
            (&self.python, "Managed Python runtime"),
            (&self.node, "Managed Node.js runtime"),
            (&self.ffmpeg.join("ffmpeg.exe"), "Managed FFmpeg runtime"),
            (&self.bgutil_script, "YouTube PO-token provider script"),
            (&self.browser_executable, "Persistent Remotion browser"),
            (&self.root.join("app.py"), "Clippy backend payload (app.py)"),
            (
                &self
                    .root
                    .join("render-service")
                    .join("dist")
                    .join("server.js"),
                "Compiled renderer",
            ),
            (
                &self.root.join("remotion").join("src").join("index.ts"),
                "Remotion source",
            ),
        ];
        let missing: Vec<String> = required
            .iter()
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

/// Build a deterministic PATH for Clippy's child processes. In particular,
/// never append the user's PATH: it can contain another Python/Node install,
/// Conda, or a user-controlled executable that shadows an application tool.
fn managed_child_path(paths: &RuntimePaths) -> Result<std::ffi::OsString, String> {
    let mut directories = Vec::new();

    if let Some(python_root) = paths.python.parent() {
        directories.push(python_root.to_path_buf());

        // The Windows PyTorch wheel stores its CUDA runtime DLLs directly in
        // torch\\lib. Setup validates CUDA kernels with this directory on PATH,
        // so the supervised backend must receive the same DLL search location.
        let torch_lib = python_root
            .join("Lib")
            .join("site-packages")
            .join("torch")
            .join("lib");
        if torch_lib.is_dir() {
            directories.push(torch_lib);
        }

        // Some CUDA dependencies are installed as separate NVIDIA wheels.
        let nvidia_root = python_root.join("Lib").join("site-packages").join("nvidia");
        for relative in ["cublas\\bin", "cudnn\\bin", "cuda_runtime\\bin"] {
            let dll_dir = nvidia_root.join(relative);
            if dll_dir.is_dir() {
                directories.push(dll_dir);
            }
        }
    }
    if let Some(node_root) = paths.node.parent() {
        directories.push(node_root.to_path_buf());
    }
    directories.push(paths.ffmpeg.clone());

    // Keep Windows system executables and DLLs available without inheriting
    // arbitrary user PATH entries. nvidia-smi is normally in System32 or the
    // NVIDIA NVSMI directory.
    if let Some(system_root) = env::var_os("SystemRoot") {
        let system_root = PathBuf::from(system_root);
        directories.push(system_root.join("System32"));
        directories.push(system_root);
    }
    if let Some(program_files) = env::var_os("ProgramFiles") {
        directories.push(
            PathBuf::from(program_files)
                .join("NVIDIA Corporation")
                .join("NVSMI"),
        );
    }

    env::join_paths(directories)
        .map_err(|error| format!("Cannot construct isolated Clippy PATH: {error}"))
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        // Child handles do not terminate their processes when dropped. Stop
        // both local services when the desktop shell exits, otherwise the
        // next launch can inherit occupied ports and attach to stale services.
        stop_child(&mut self.renderer);
        stop_child(&mut self.backend);
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
        fs::create_dir_all(&paths.output)
            .map_err(|e| format!("Cannot create output directory: {e}"))?;
        fs::create_dir_all(&paths.uploads)
            .map_err(|e| format!("Cannot create uploads directory: {e}"))?;
        fs::create_dir_all(&paths.library)
            .map_err(|e| format!("Cannot create Library directory: {e}"))?;
        fs::create_dir_all(&paths.models)
            .map_err(|e| format!("Cannot create models directory: {e}"))?;
        fs::create_dir_all(&paths.logs).map_err(|e| format!("Cannot create log directory: {e}"))?;
        let child_path = managed_child_path(&paths)?;
        let job = ProcessJob::new()?;
        let backend_port = allocate_loopback_port()?;
        let mut renderer_port = allocate_loopback_port()?;
        while renderer_port == backend_port {
            renderer_port = allocate_loopback_port()?;
        }
        let backend_port_arg = backend_port.to_string();
        let renderer_port_arg = renderer_port.to_string();
        let api_token = generate_api_token()?;

        let backend_log = open_log(&paths.logs.join("backend.log"))?;
        let renderer_log = open_log(&paths.logs.join("renderer.log"))?;
        let renderer_stdout = renderer_log.try_clone().map_err(|e| e.to_string())?;
        let mut backend_command = Command::new(&paths.python);
        backend_command
            .args([
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                BACKEND_HOST,
                "--port",
                &backend_port_arg,
                "--no-access-log",
            ])
            .current_dir(&paths.root)
            // Do not allow a user's Python/Conda environment to influence the
            // interpreter or imports. The executable is always Clippy's private
            // Python and the only application import path is the packaged app.
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONUSERBASE")
            .env_remove("PYTHONSTARTUP")
            .env_remove("PYTHONEXECUTABLE")
            .env_remove("VIRTUAL_ENV")
            .env_remove("CONDA_PREFIX")
            .env_remove("CONDA_DEFAULT_ENV")
            .env_remove("CONDA_EXE")
            .env("PYTHONPATH", &paths.root)
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONUTF8", "1")
            .env("CLIPPY_DATA_DIR", &paths.data_root)
            .env("OUTPUT_DIR", &paths.output)
            .env("UPLOAD_DIR", &paths.uploads)
            .env("CLIPPY_LIBRARY_DIR", &paths.library)
            .env("CLIPPY_MODELS_DIR", &paths.models)
            .env("CLIPPY_SETTINGS_PATH", &paths.settings_file)
            .env("CLIPPY_DESKTOP_MODE", "1")
            .env("REFERENCE_TEMPLATES_DIR", &paths.references)
            .env("CLIPPY_NODE_EXE", &paths.node)
            .env("HF_HOME", paths.models.join("huggingface"))
            .env(
                "HUGGINGFACE_HUB_CACHE",
                paths.models.join("huggingface").join("hub"),
            )
            .env("TORCH_HOME", paths.models.join("torch"))
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .env_remove("NODE_PATH")
            .env_remove("NODE_OPTIONS")
            .env_remove("NPM_CONFIG_PREFIX")
            .env_remove("NPM_CONFIG_USERCONFIG")
            .env("PATH", &child_path)
            .env(
                "RENDER_SERVICE_URL",
                format!("http://{RENDERER_HOST}:{renderer_port}"),
            )
            .env("BGUTIL_SCRIPT_PATH", &paths.bgutil_script)
            .env("REMOTION_BROWSER_EXECUTABLE", &paths.browser_executable)
            .env("HOST", BACKEND_HOST)
            .env("PORT", backend_port_arg.clone())
            .env("CLIPPY_API_TOKEN", &api_token);
        apply_local_only_environment(&mut backend_command);
        let mut backend = backend_command
            .stdout(Stdio::from(
                backend_log.try_clone().map_err(|e| e.to_string())?,
            ))
            .stderr(Stdio::from(backend_log))
            .spawn()
            .map_err(|e| format!("Could not start the Clippy backend: {e}"))?;
        if let Err(error) = job.assign(&backend) {
            let _ = backend.kill();
            let _ = backend.wait();
            return Err(error);
        }

        let mut renderer_command = Command::new(&paths.node);
        renderer_command
            .arg(
                paths
                    .root
                    .join("render-service")
                    .join("dist")
                    .join("server.js"),
            )
            .current_dir(paths.root.join("render-service"))
            .env("HOST", RENDERER_HOST)
            .env("NODE_ENV", "production")
            .env("PORT", renderer_port_arg.clone())
            .env("OUTPUT_DIR", &paths.output)
            .env("CLIPPY_API_TOKEN", &api_token)
            .env_remove("NODE_PATH")
            .env_remove("NODE_OPTIONS")
            .env_remove("NPM_CONFIG_PREFIX")
            .env_remove("NPM_CONFIG_USERCONFIG")
            .env("PATH", &child_path)
            .env("REMOTION_BROWSER_EXECUTABLE", &paths.browser_executable)
            .env("REMOTION_BUNDLE_PATH", paths.root.join("remotion"));
        apply_local_only_environment(&mut renderer_command);
        let renderer = renderer_command
            .stdout(Stdio::from(renderer_stdout))
            .stderr(Stdio::from(renderer_log))
            .spawn();

        let mut renderer = match renderer {
            Ok(child) => child,
            Err(error) => {
                let _ = backend.kill();
                let _ = backend.wait();
                return Err(format!("Could not start the Remotion renderer: {error}"));
            }
        };
        if let Err(error) = job.assign(&renderer) {
            let _ = renderer.kill();
            let _ = renderer.wait();
            let _ = backend.kill();
            let _ = backend.wait();
            return Err(error);
        }

        if let Err(error) = wait_for_health(
            &mut backend,
            backend_port,
            "/health/ready",
            Duration::from_secs(300),
        ) {
            let _ = renderer.kill();
            let _ = renderer.wait();
            let _ = backend.kill();
            let _ = backend.wait();
            return Err(format!(
                "Backend startup failed: {error}. See {}",
                paths.logs.join("backend.log").display()
            ));
        }
        if let Err(error) = wait_for_health(
            &mut renderer,
            renderer_port,
            "/health",
            Duration::from_secs(180),
        ) {
            let _ = renderer.kill();
            let _ = renderer.wait();
            let _ = backend.kill();
            let _ = backend.wait();
            return Err(format!(
                "Renderer startup failed: {error}. See {}",
                paths.logs.join("renderer.log").display()
            ));
        }

        self.backend = Some(backend);
        self.renderer = Some(renderer);
        self.paths = Some(paths);
        self.job = Some(job);
        self.backend_port = backend_port;
        self.renderer_port = renderer_port;
        self.api_token = Some(api_token);
        self.status()
    }

    pub fn data_directory(&self) -> Result<PathBuf, String> {
        self.paths
            .as_ref()
            .map(|paths| paths.data_root.clone())
            .ok_or_else(|| "Clippy data directory is unavailable because services are not running.".to_string())
    }

    fn post_backend_maintenance(&self, path: &str, operation: &str) -> Result<(), String> {
        if self.backend_port == 0 {
            return Err("Clippy services must be running before this maintenance operation.".into());
        }
        let token = self.api_token.as_deref()
            .ok_or_else(|| "Clippy's local API token is unavailable.".to_string())?;
        let url = format!("http://{BACKEND_HOST}:{}{path}", self.backend_port);
        match ureq::post(&url)
            .timeout(Duration::from_secs(65))
            .set("X-Clippy-Token", token)
            .call()
        {
            Ok(response) if response.status() == 200 => Ok(()),
            Ok(response) => {
                let body = response.into_string().unwrap_or_default();
                Err(format!("Clippy refused {operation}: {body}"))
            }
            Err(ureq::Error::Status(status, response)) => {
                let body = response.into_string().unwrap_or_default();
                Err(format!("Clippy refused {operation} (HTTP {status}): {body}"))
            }
            Err(ureq::Error::Transport(error)) => {
                Err(format!("Could not verify that Clippy is idle before {operation}: {error}"))
            }
        }
    }

    pub fn prepare_update(&self) -> Result<(), String> {
        self.post_backend_maintenance(
            "/api/desktop/update/prepare",
            "the update because work is still active",
        )
    }

    pub fn prepare_data_move(&self) -> Result<(), String> {
        self.post_backend_maintenance(
            "/api/library/storage/prepare-move",
            "the data move because work is still active",
        )
    }

    pub fn api_token(&self) -> Result<String, String> {
        self.api_token.clone().ok_or_else(|| {
            "Clippy's local API token is not available because services are not running."
                .to_string()
        })
    }

    pub fn stop(&mut self) -> Result<ServiceStatus, String> {
        stop_child(&mut self.renderer);
        stop_child(&mut self.backend);
        self.job.take(); // Closing the job also terminates any surviving descendants.
        self.backend_port = 0;
        self.renderer_port = 0;
        self.api_token = None;
        self.status()
    }

    pub fn status(&mut self) -> Result<ServiceStatus, String> {
        let backend = child_status(&mut self.backend);
        let renderer = child_status(&mut self.renderer);
        let paths = self.paths.clone().or_else(|| RuntimePaths::discover().ok());
        let backend_url = if self.backend_port > 0 {
            format!("http://{BACKEND_HOST}:{}", self.backend_port)
        } else {
            String::new()
        };
        let renderer_url = if self.renderer_port > 0 {
            format!("http://{RENDERER_HOST}:{}", self.renderer_port)
        } else {
            String::new()
        };
        let output_directory = paths
            .as_ref()
            .map(|p| p.output.display().to_string())
            .unwrap_or_default();
        let setup_required = paths
            .as_ref()
            .map(|p| p.validate().is_err())
            .unwrap_or(true);
        let message = if setup_required {
            "First-run dependency setup is required before Clippy can start.".to_string()
        } else if backend == "running" && renderer == "running" {
            "Clippy services are ready.".to_string()
        } else {
            "Clippy services are not running.".to_string()
        };
        Ok(ServiceStatus {
            backend,
            renderer,
            backend_url,
            renderer_url,
            output_directory,
            setup_required,
            message,
        })
    }
}

fn open_log(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| format!("Cannot open log {}: {e}", path.display()))
}

fn wait_for_health(
    child: &mut Child,
    port: u16,
    path: &str,
    timeout: Duration,
) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            return Err(format!("service exited early with status {status}"));
        }
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            use std::io::{Read, Write};
            stream.set_read_timeout(Some(Duration::from_secs(2))).ok();
            let request =
                format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok()
                    && response.starts_with("HTTP/1.1 200")
                {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!(
        "health endpoint {path} on 127.0.0.1:{port} did not become ready before timeout"
    ))
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

#[cfg(test)]
mod managed_path_tests {
    use super::{
        apply_local_only_environment, managed_child_path, RuntimePaths, HOSTED_ENV_DENYLIST,
    };
    use std::{
        env, fs,
        path::PathBuf,
        time::{SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn local_backend_and_renderer_environment_is_fail_closed() {
        use std::process::Command;

        let mut command = Command::new("python");
        command.env("BILLING_ENABLED", "true");
        for name in HOSTED_ENV_DENYLIST {
            command.env(*name, "must-not-reach-desktop");
        }

        apply_local_only_environment(&mut command);

        let configured: std::collections::HashMap<String, Option<String>> = command
            .get_envs()
            .map(|(key, value)| {
                (
                    key.to_string_lossy().into_owned(),
                    value.map(|value| value.to_string_lossy().into_owned()),
                )
            })
            .collect();

        assert_eq!(
            configured.get("CLIPPY_DESKTOP_MODE"),
            Some(&Some("1".to_string()))
        );
        assert_eq!(
            configured.get("BILLING_ENABLED"),
            Some(&Some("0".to_string()))
        );
        for name in HOSTED_ENV_DENYLIST {
            assert_eq!(
                configured.get(*name),
                Some(&None),
                "hosted variable {name} must be removed from desktop children"
            );
        }
    }

    #[test]
    #[cfg(windows)]
    fn closing_setup_job_reaps_waiting_setup_process() {
        use std::{
            io::Write,
            process::{Command, Stdio},
        };
        let shell = PathBuf::from(env::var_os("SystemRoot").unwrap())
            .join("System32/WindowsPowerShell/v1.0/powershell.exe");
        let job = super::ProcessJob::new().unwrap();
        let mut child = Command::new(shell)
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if ([Console]::ReadLine() -ne 'GO') { exit 1 }; Start-Sleep -Seconds 60",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        job.assign(&child).unwrap();
        child.stdin.take().unwrap().write_all(b"GO\n").unwrap();
        drop(job);
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            if child.try_wait().unwrap().is_some() {
                break;
            }
            if std::time::Instant::now() > deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("Setup survived cleanup job closure");
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
    }

    #[test]
    fn includes_the_windows_pytorch_cuda_dll_directory() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = env::temp_dir().join(format!(
            "clippy-managed-path-{}-{nonce}",
            std::process::id()
        ));
        let python_root = root.join("runtime").join("python");
        let torch_lib = python_root
            .join("Lib")
            .join("site-packages")
            .join("torch")
            .join("lib");
        fs::create_dir_all(&torch_lib).unwrap();

        let paths = RuntimePaths {
            root: root.join("app").join("current"),
            python: python_root.join("python.exe"),
            node: root.join("runtime").join("node").join("node.exe"),
            ffmpeg: root.join("runtime").join("ffmpeg").join("bin"),
            bgutil_script: PathBuf::from("bgutil-provider/server/build/generate_once.js"),
            browser_executable: PathBuf::from("browser/headless-shell/chrome-headless-shell.exe"),
            data_root: root.join("data"),
            output: root.join("data").join("output"),
            uploads: root.join("data").join("uploads"),
            library: root.join("data").join("library"),
            models: root.join("data").join("models"),
            settings_file: root.join("settings.json"),
            references: root.join("data/reference_templates"),
            logs: root.join("logs"),
        };

        let path = managed_child_path(&paths).unwrap();
        let entries: Vec<PathBuf> = env::split_paths(&path).collect();
        assert!(
            entries.iter().any(|entry| entry == &torch_lib),
            "supervised PATH must include the CUDA DLL directory: {entries:?}"
        );

        fs::remove_dir_all(root).unwrap();
    }
}
