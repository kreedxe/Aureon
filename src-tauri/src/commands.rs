use crate::backend::BackendState;
use serde::Serialize;
use tauri::State;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendConfig {
    base_url: String,
    token: String,
}

#[tauri::command]
pub fn get_backend_config(state: State<'_, BackendState>) -> Result<BackendConfig, String> {
    let backend = state
        .0
        .lock()
        .map_err(|_| "Backend state is unavailable.".to_string())?;
    match &backend.runtime {
        Ok(runtime) => Ok(BackendConfig {
            base_url: runtime.base_url.clone(),
            token: runtime.token.clone(),
        }),
        Err(error) => Err(error.clone()),
    }
}
