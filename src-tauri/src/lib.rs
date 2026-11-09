mod backend;
mod commands;

use backend::BackendState;
use tauri::Manager;

pub fn run() {
    let backend = BackendState::default();
    backend.start();

    tauri::Builder::default()
        .manage(backend)
        .invoke_handler(tauri::generate_handler![commands::get_backend_config])
        .build(tauri::generate_context!())
        .expect("error while building desktop application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                app.state::<BackendState>().stop();
            }
        });
}
