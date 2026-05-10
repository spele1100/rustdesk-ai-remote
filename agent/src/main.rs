use axum::{
    extract::ws::{Message, WebSocket, WebSocketUpgrade},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use enigo::{Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use futures::StreamExt;
use image::ImageFormat;
use serde::{Deserialize, Serialize};
use enigo::Axis;
use std::sync::Arc;
use tokio::sync::Mutex;
use tower_http::cors::CorsLayer;
use tracing::{error, info};

// ── Input command types ────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "action")]
enum InputCommand {
    #[serde(rename = "click")]
    Click {
        x: i32,
        y: i32,
        #[serde(default = "default_button")]
        button: String,
    },
    #[serde(rename = "double_click")]
    DoubleClick { x: i32, y: i32 },
    #[serde(rename = "type")]
    TypeText { text: String },
    #[serde(rename = "key_press")]
    KeyPress { keys: Vec<String> },
    #[serde(rename = "scroll")]
    Scroll {
        x: i32,
        y: i32,
        delta: i32,
    },
    #[serde(rename = "drag")]
    Drag {
        from: (i32, i32),
        to: (i32, i32),
    },
    #[serde(rename = "screenshot")]
    Screenshot,
    #[serde(rename = "wait")]
    Wait { ms: u64 },
    #[serde(rename = "emergency_stop")]
    EmergencyStop,
}

fn default_button() -> String {
    "left".into()
}

#[derive(Serialize)]
struct CommandResponse {
    ok: bool,
    message: String,
}

// ── Screenshot capture ─────────────────────────────────────────────

fn capture_screenshot_png() -> Result<Vec<u8>, String> {
    let monitors = xcap::Monitor::all().map_err(|e| format!("Failed to list monitors: {e}"))?;
    let monitor = monitors.first().ok_or("No monitors found")?;
    let image = monitor.capture_image().map_err(|e| format!("Capture failed: {e}"))?;
    let mut buf = Vec::new();
    image
        .write_to(&mut std::io::Cursor::new(&mut buf), ImageFormat::Png)
        .map_err(|e| format!("PNG encode failed: {e}"))?;
    Ok(buf)
}

// ── Input execution ────────────────────────────────────────────────

fn execute_command(cmd: &InputCommand) -> Result<String, String> {
    let mut enigo = Enigo::new(&Settings::default()).map_err(|e| format!("Enigo init: {e}"))?;

    match cmd {
        InputCommand::Click { x, y, button } => {
            enigo
                .move_mouse(*x, *y, Coordinate::Abs)
                .map_err(|e| format!("Move: {e}"))?;
            let btn = match button.as_str() {
                "right" => Button::Right,
                "middle" => Button::Middle,
                _ => Button::Left,
            };
            enigo.button(btn, Direction::Click).map_err(|e| format!("Click: {e}"))?;
            Ok(format!("Clicked {} at ({}, {})", button, x, y))
        }
        InputCommand::DoubleClick { x, y } => {
            enigo
                .move_mouse(*x, *y, Coordinate::Abs)
                .map_err(|e| format!("Move: {e}"))?;
            enigo.button(Button::Left, Direction::Click).map_err(|e| format!("Click1: {e}"))?;
            std::thread::sleep(std::time::Duration::from_millis(50));
            enigo.button(Button::Left, Direction::Click).map_err(|e| format!("Click2: {e}"))?;
            Ok(format!("Double-clicked at ({}, {})", x, y))
        }
        InputCommand::TypeText { text } => {
            enigo.text(text).map_err(|e| format!("Type: {e}"))?;
            Ok(format!("Typed {} chars", text.len()))
        }
        InputCommand::KeyPress { keys } => {
            // Press all modifier keys first, then the last key, then release
            let enigo_keys: Vec<Key> = keys
                .iter()
                .map(|k| str_to_key(k))
                .collect::<Result<Vec<_>, _>>()?;

            // Hold all keys
            for key in &enigo_keys {
                enigo.key(*key, Direction::Press).map_err(|e| format!("Key press: {e}"))?;
            }
            // Release all in reverse
            for key in enigo_keys.iter().rev() {
                enigo.key(*key, Direction::Release).map_err(|e| format!("Key release: {e}"))?;
            }
            Ok(format!("Key press: {}", keys.join("+")))
        }
        InputCommand::Scroll { x, y, delta } => {
            enigo
                .move_mouse(*x, *y, Coordinate::Abs)
                .map_err(|e| format!("Move: {e}"))?;
            let scroll_amount = *delta * 5; // 5 lines per unit
            enigo
                .scroll(scroll_amount, Axis::Vertical)
                .map_err(|e| format!("Scroll: {e}"))?;
            Ok(format!("Scrolled {} at ({}, {})", delta, x, y))
        }
        InputCommand::Drag { from, to } => {
            enigo
                .move_mouse(from.0, from.1, Coordinate::Abs)
                .map_err(|e| format!("Move to start: {e}"))?;
            enigo.button(Button::Left, Direction::Press).map_err(|e| format!("Press: {e}"))?;
            std::thread::sleep(std::time::Duration::from_millis(50));
            enigo
                .move_mouse(to.0, to.1, Coordinate::Abs)
                .map_err(|e| format!("Move to end: {e}"))?;
            enigo.button(Button::Left, Direction::Release).map_err(|e| format!("Release: {e}"))?;
            Ok(format!("Dragged from {:?} to {:?}", from, to))
        }
        InputCommand::Screenshot => {
            // Just acknowledge — the response will have the screenshot
            Ok("Screenshot requested".into())
        }
        InputCommand::Wait { ms } => {
            std::thread::sleep(std::time::Duration::from_millis(*ms));
            Ok(format!("Waited {}ms", ms))
        }
        InputCommand::EmergencyStop => {
            Err("EMERGENCY_STOP".into())
        }
    }
}

fn str_to_key(s: &str) -> Result<Key, String> {
    Ok(match s.to_lowercase().as_str() {
        "ctrl" | "control" => Key::Control,
        "alt" => Key::Alt,
        "shift" => Key::Shift,
        "meta" | "win" | "cmd" | "super" => Key::Meta,
        "enter" | "return" => Key::Return,
        "tab" => Key::Tab,
        "escape" | "esc" => Key::Escape,
        "backspace" => Key::Backspace,
        "delete" | "del" => Key::Delete,
        "home" => Key::Home,
        "end" => Key::End,
        "pageup" => Key::PageUp,
        "pagedown" => Key::PageDown,
        "up" => Key::UpArrow,
        "down" => Key::DownArrow,
        "left" => Key::LeftArrow,
        "right" => Key::RightArrow,
        "space" => Key::Space,
        "f1" => Key::F1,
        "f2" => Key::F2,
        "f3" => Key::F3,
        "f4" => Key::F4,
        "f5" => Key::F5,
        "f6" => Key::F6,
        "f7" => Key::F7,
        "f8" => Key::F8,
        "f9" => Key::F9,
        "f10" => Key::F10,
        "f11" => Key::F11,
        "f12" => Key::F12,
        c if c.len() == 1 => Key::Unicode(c.chars().next().unwrap()),
        _ => return Err(format!("Unknown key: {s}")),
    })
}

// ── HTTP handlers ──────────────────────────────────────────────────

async fn screenshot_handler() -> impl IntoResponse {
    match tokio::task::spawn_blocking(capture_screenshot_png).await {
        Ok(Ok(png)) => (
            StatusCode::OK,
            [(axum::http::header::CONTENT_TYPE, "image/png")],
            png,
        ),
        Ok(Err(e)) => {
            error!("Screenshot failed: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, [(axum::http::header::CONTENT_TYPE, "text/plain")], e.into_bytes())
        }
        Err(e) => {
            error!("Task join error: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, [(axum::http::header::CONTENT_TYPE, "text/plain")], "Task panicked".into())
        }
    }
}

async fn input_handler(Json(cmd): Json<InputCommand>) -> impl IntoResponse {
    info!("Received command: {:?}", cmd);

    if matches!(cmd, InputCommand::EmergencyStop) {
        return (
            StatusCode::OK,
            Json(CommandResponse {
                ok: false,
                message: "EMERGENCY_STOP".into(),
            }),
        );
    }

    let result = tokio::task::spawn_blocking(move || execute_command(&cmd)).await;

    match result {
        Ok(Ok(msg)) => (
            StatusCode::OK,
            Json(CommandResponse { ok: true, message: msg }),
        ),
        Ok(Err(e)) => {
            error!("Command failed: {e}");
            (
                StatusCode::BAD_REQUEST,
                Json(CommandResponse { ok: false, message: e }),
            )
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(CommandResponse {
                ok: false,
                message: format!("Task panicked: {e}"),
            }),
        )
    }
}

async fn ws_handler(ws: WebSocketUpgrade) -> impl IntoResponse {
    ws.on_upgrade(handle_socket)
}

async fn handle_socket(mut socket: WebSocket) {
    info!("WebSocket client connected");

    while let Some(msg) = socket.recv().await {
        match msg {
            Ok(Message::Text(text)) => {
                let cmd: InputCommand = match serde_json::from_str(&text) {
                    Ok(c) => c,
                    Err(e) => {
                        let _ = socket
                            .send(Message::Text(format!(r#"{{"ok":false,"error":"{e}"}}"#)))
                            .await;
                        continue;
                    }
                };

                if matches!(cmd, InputCommand::EmergencyStop) {
                    let _ = socket
                        .send(Message::Text(r#"{"ok":false,"message":"EMERGENCY_STOP"}"#.into()))
                        .await;
                    break;
                }

                if matches!(cmd, InputCommand::Screenshot) {
                    match tokio::task::spawn_blocking(capture_screenshot_png).await {
                        Ok(Ok(png)) => {
                            let b64 = base64::encode(&png);
                            let _ = socket
                                .send(Message::Text(format!(
                                    r#"{{"type":"screenshot","data":"{b64}"}}"#
                                )))
                                .await;
                        }
                        Ok(Err(e)) => {
                            let _ = socket
                                .send(Message::Text(format!(r#"{{"ok":false,"error":"{e}"}}"#)))
                                .await;
                        }
                        Err(e) => {
                            let _ = socket
                                .send(Message::Text(format!(
                                    r#"{{"ok":false,"error":"panic: {e}"}}"#
                                )))
                                .await;
                        }
                    }
                    continue;
                }

                let _cmd_str = serde_json::to_string(&cmd).unwrap_or_default();
                let result = tokio::task::spawn_blocking(move || execute_command(&cmd)).await;

                let resp = match result {
                    Ok(Ok(msg)) => format!(r#"{{"ok":true,"message":"{msg}"}}"#),
                    Ok(Err(e)) => format!(r#"{{"ok":false,"error":"{e}"}}"#),
                    Err(e) => format!(r#"{{"ok":false,"error":"panic: {e}"}}"#),
                };
                let _ = socket.send(Message::Text(resp)).await;
            }
            Ok(Message::Close(_)) => break,
            Err(e) => {
                error!("WS error: {e}");
                break;
            }
            _ => {}
        }
    }
    info!("WebSocket client disconnected");
}

async fn health_handler() -> &'static str {
    "ok"
}

// ── Main ───────────────────────────────────────────────────────────

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = Router::new()
        .route("/screenshot", get(screenshot_handler))
        .route("/input", post(input_handler))
        .route("/stream", get(ws_handler))
        .route("/health", get(health_handler))
        .layer(CorsLayer::permissive());

    let addr = "0.0.0.0:5800";
    info!("🤖 AI Remote Agent listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
