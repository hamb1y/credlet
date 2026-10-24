use std::time::Duration;

/// The shared JS client supplies an already encrypted envelope. This adapter
/// only performs HTTP from the native shell, avoiding WebView mixed-content
/// restrictions. It receives no master password or decrypted vault records.
#[tauri::command]
async fn encrypted_exchange(
    origin: String,
    envelope: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let mut url = reqwest::Url::parse(&origin).map_err(|_| "Invalid server address.")?;
    if url.scheme() != "http"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Use an HTTP server origin without a path, credentials or query.".into());
    }
    let body = serde_json::to_vec(&envelope).map_err(|_| "Invalid encrypted envelope.")?;
    if body.len() > 256 * 1024
        || envelope.get("v").and_then(|v| v.as_u64()) != Some(1)
        || envelope.get("box").and_then(|v| v.as_str()).is_none()
    {
        return Err("Invalid encrypted envelope.".into());
    }
    url.set_path("/v1/exchange");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .build()
        .map_err(|_| "HTTP client unavailable.")?;
    let mut response = client
        .post(url)
        .header("Content-Type", "application/json")
        .body(body)
        .send()
        .await
        .map_err(|_| "Could not reach your Credlet server.")?;
    if !response.status().is_success() {
        return Err(
            "Server rejected the encrypted connection. Check its address and pinned key.".into(),
        );
    }
    let mut received = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "Incomplete server response.")?
    {
        if received.len() + chunk.len() > 16 * 1024 * 1024 {
            return Err("Server response is too large.".into());
        }
        received.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&received).map_err(|_| "Invalid encrypted server response.".into())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![encrypted_exchange])
        .run(tauri::generate_context!())
        .expect("Could not start Credlet");
}
