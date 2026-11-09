#[cfg(unix)]
use process_wrap::std::ProcessGroup;
use process_wrap::std::{ChildWrapper, CommandWrap};
use reqwest::blocking::Client;
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use uuid::Uuid;

pub struct BackendState(pub Mutex<BackendManager>);

pub struct BackendManager {
    pub runtime: Result<BackendRuntime, String>,
    child: Option<Box<dyn ChildWrapper>>,
}

pub struct BackendRuntime {
    pub base_url: String,
    pub token: String,
}

impl Default for BackendState {
    fn default() -> Self {
        Self(Mutex::new(BackendManager {
            runtime: Err("Python backend has not started.".to_string()),
            child: None,
        }))
    }
}

impl BackendState {
    pub fn start(&self) {
        let result = start_backend();
        if let Ok(mut state) = self.0.lock() {
            match result {
                Ok((runtime, child)) => {
                    state.runtime = Ok(runtime);
                    state.child = Some(child);
                }
                Err(error) => {
                    eprintln!("Python backend startup failed: {error}");
                    state.runtime = Err(error);
                }
            }
        } else {
            eprintln!("Python backend startup failed: application state is unavailable.");
        }
    }

    pub fn stop(&self) {
        let Ok(mut state) = self.0.lock() else {
            eprintln!("Could not stop Python backend: application state is unavailable.");
            return;
        };
        if let Some(mut child) = state.child.take() {
            #[cfg(unix)]
            {
                if let Err(error) = child.signal(libc::SIGTERM) {
                    eprintln!("Could not gracefully stop Python backend: {error}");
                }
                let deadline = Instant::now() + Duration::from_secs(3);
                while Instant::now() < deadline {
                    match child.try_wait() {
                        Ok(Some(_)) => {
                            if let Err(error) = child.kill() {
                                if error.kind() != std::io::ErrorKind::NotFound {
                                    eprintln!("Could not stop remaining Python backend processes: {error}");
                                }
                            }
                            return;
                        }
                        Ok(None) => thread::sleep(Duration::from_millis(50)),
                        Err(error) => {
                            eprintln!("Could not inspect Python backend shutdown: {error}");
                            break;
                        }
                    }
                }
            }
            if let Err(error) = child.kill() {
                eprintln!("Could not stop Python backend: {error}");
            }
        }
    }
}

fn start_backend() -> Result<(BackendRuntime, Box<dyn ChildWrapper>), String> {
    if !cfg!(debug_assertions) {
        return Err(
            "Packaged backend executable is not configured. See the packaging strategy in README.md."
                .to_string(),
        );
    }

    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("Could not reserve a local backend port: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("Could not determine the local backend port: {error}"))?
        .port();
    drop(listener);

    let token = Uuid::new_v4().to_string();
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or_else(|| "Could not locate the application root directory.".to_string())?;
    let backend_dir = root.join("backend");
    let mut command = Command::new("uv");
    command
        .args([
            "run",
            "--project",
            backend_dir
                .to_str()
                .ok_or_else(|| "Backend directory path is not valid UTF-8.".to_string())?,
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--reload",
        ])
        .current_dir(&backend_dir)
        .env("AUREON_SESSION_TOKEN", &token)
        .stdin(Stdio::null());

    let mut wrapped = CommandWrap::from(command);
    #[cfg(unix)]
    wrapped.wrap(ProcessGroup::leader());
    #[cfg(windows)]
    wrapped.wrap(process_wrap::std::JobObject);

    let mut child = wrapped.spawn().map_err(|error| {
        format!("Could not start the Python backend with `uv`. Install uv and run `uv sync` in backend/: {error}")
    })?;
    let base_url = format!("http://127.0.0.1:{port}");
    let client = match Client::builder()
        .timeout(Duration::from_millis(500))
        .build()
    {
        Ok(client) => client,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "Could not prepare backend readiness checks: {error}"
            ));
        }
    };
    let deadline = Instant::now() + Duration::from_secs(30);

    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(status)) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Python backend exited before becoming ready ({status}). Check the backend startup logs."));
            }
            Ok(None) => {}
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Could not inspect Python backend startup: {error}"));
            }
        }
        match client
            .get(format!("{base_url}/health"))
            .header("X-Session-Token", &token)
            .send()
        {
            Ok(response) => {
                if response.status().is_success() {
                    println!("Python backend ready at {base_url}");
                    return Ok((BackendRuntime { base_url, token }, child));
                }
                let status = response.status();
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Python backend readiness check returned HTTP {status}. Check its session token and startup logs."));
            }
            Err(error) if !error.is_connect() => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Python backend readiness check failed: {error}"));
            }
            _ => thread::sleep(Duration::from_millis(150)),
        }
    }

    let _ = child.kill();
    let _ = child.wait();
    Err("Python backend did not become ready within 30 seconds. Check the backend startup logs and run `uv sync` in backend/.".to_string())
}
