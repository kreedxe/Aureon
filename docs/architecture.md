# Aureon architecture

## Responsibilities

- **React and TypeScript** render the recording studio and product catalog and collect user interaction. `MediaRecorder` captures microphone audio in the desktop webview. Hooks coordinate UI state; `src/lib/api.ts` performs HTTP requests. The frontend does not contain transcription, application persistence, or database logic.
- **FastAPI** validates requests, owns temporary recording files and metadata, coordinates transcription and AI jobs, serves product CRUD/search, and runs faster-whisper and llama.cpp locally. It is independent of React and Tauri and binds only to `127.0.0.1`.
- **SQLite** stores the shop product catalog persistently in the OS application-data directory. `ProductRepository` owns database connections, schema initialization, query filtering/sorting, and row mapping. SQLite access is only in Python.
- **Tauri and Rust** create the native window, generate the per-launch token and local port, start the backend, wait for authenticated readiness, provide API configuration through a narrow Tauri command, and stop the backend on exit.

## Recording and transcription flow

1. React requests microphone access through `getUserMedia`; the OS/webview permission prompt and error are surfaced to the user.
2. `MediaRecorder` captures audio in the webview. The completed Blob is retained for playback in the frontend session and posted as multipart audio to FastAPI.
3. FastAPI validates the upload and stores the file in a temporary directory created for the backend process. Recording metadata and file paths exist only in the process's in-memory session store.
4. React requests a transcription with Auto or an explicit language (`uz`, `ru`, or `en`). FastAPI queues one job and returns its identifier; job status is polled without blocking the UI.
5. The Python service lazily initializes the multilingual faster-whisper `small` model with CPU int8 inference. First-use download byte counts are reported through the transcription job; model initialization and segment-based transcription have separate progress stages. It returns detected language and Whisper's language probability when available, and never uses cloud recognition or translates speech.
6. FastAPI shuts down the worker and removes the session's temporary directory as the backend exits. The model cache is separate in the OS user cache directory and persists between sessions; first-use model download needs internet, while cached inference is local.

## Local AI text flow

1. The recording detail view sends an AI operation request for a recording that already has a supported Uzbek, Russian, or English transcript.
2. FastAPI snapshots the original transcript and queues one AI job on its dedicated worker. While it runs, the frontend polls job progress asynchronously; recording playback and navigation remain responsive.
3. On the first AI job only, `LocalAIEngine` downloads Qwen3 1.7B Instruct GGUF Q4_K_M from `unsloth/Qwen3-1.7B-GGUF` into the persistent `platformdirs` user cache (about 1.1 GB). The engine lazily loads one llama.cpp instance and reuses it for subsequent operations and app sessions; it does not initialize at backend startup.
4. The local model receives transcript text and a task-specific instruction for summary, key points, action items/decisions, or explicit translation. Summary, key points, and action extraction are instructed to preserve the source language. Translation requires a different supported target language.
5. Python parses the model's JSON and validates the operation-specific Pydantic schema. Only a validated result is saved in the recording's separate `ai_results` map; the source transcript is unchanged. The frontend renders the result in its matching AI tab.

The model download is the only AI feature that needs internet access. Transcript content is processed locally and is not sent to Hugging Face or any inference API. Once cached, model inference works offline. AI is optional: recording and Whisper transcription continue to work if the model has not been downloaded or cannot be loaded. The current llama.cpp build uses CPU inference and requires additional RAM for model weights and context; available memory and CPU speed affect latency.

## Product catalog data flow

1. The React Products workspace sends validated CRUD, search, filter, and sort requests to authenticated FastAPI endpoints.
2. FastAPI validates each product with Pydantic and delegates reads/writes to `ProductRepository`.
3. The repository opens short-lived SQLite connections to a database file under `platformdirs.user_data_dir("Aureon", "Aureon")`. It stores exact prices as decimal text, structured specifications as JSON, and created/updated timestamps as ISO-8601.
4. Availability reported to the UI is derived from catalog state: an active item with zero stock is reported out of stock; a discontinued item stays discontinued. Product facts are not inferred by the frontend or model.

The SQLite database persists across application sessions and is independent of temporary session audio. The schema is initialized idempotently when the backend starts. No product information is sent off-device.

The optional product-description endpoint accepts only the permitted catalog fields and calls the same lazily loaded local Qwen engine used for transcript tools. Inference is serialized with other local LLM work. It returns a validated draft with `requires_review: true`; it does not persist or directly modify a product. The UI places the draft in an editable field and leaves saving to the shop owner.

## Backend request flow and security

1. Rust creates a random UUID v4 token and chooses an ephemeral loopback port.
2. In development, Rust starts `uv run --project backend uvicorn app.main:app --host 127.0.0.1 --port <port> --reload`, passing the token in the backend process environment.
3. Rust polls authenticated `GET /health` before advertising the backend configuration.
4. React invokes `get_backend_config` through Tauri IPC and obtains the URL and token from Rust, not source constants.
5. React sends the token in `X-Session-Token`; FastAPI compares it in constant time and validates endpoint inputs and outputs with Pydantic.
6. On application exit, Rust terminates and waits for the child process group (Unix) or Job Object (Windows).

The API binds exclusively to IPv4 loopback; a random port and random token are created for each process session. The token protects against unrelated local requests, not a compromised same-user process or malicious frontend bundle. Tauri capabilities do not grant shell or unrestricted filesystem access.

## Session state and concurrency

Recording files, names, timestamps, durations, AI results, and job status are process-local. Audio is not persisted across sessions. Product data is persistent in SQLite. The backend accepts at most one active transcription or AI job at a time to avoid overlapping inference against shared state; concurrent starts receive a conflict response. Completed or failed transcription and AI operations can be run again for a recording while it remains in the session. The Qwen model cache is intentionally persistent and separate from session audio and product data.

The UI keeps uploaded audio Blobs in memory as object URLs for playback. Switching between recordings does not discard them. Deletion revokes the associated object URL and removes its backend temporary file. The backend enforces upload size and supported media-type constraints and reports invalid or corrupt audio errors.

## Packaging direction and limitations

Development starts the project environment through uv without assuming a Python installation path. The current release launcher explicitly errors until a target-specific PyInstaller executable is configured as a Tauri sidecar/resource. The macOS Apple Silicon `.app` and `.dmg` bundle build has been verified, but packaged release startup is not functional until that sidecar is supplied. Windows/Linux builds, packaged microphone behavior, and hardware-specific audio codecs require validation on their respective platforms before release compatibility can be claimed. Whisper and Qwen models are downloaded and cached on first use; neither is bundled.

Live customer conversations, a real-time VAD/ASR/LLM/TTS pipeline, product retrieval tools in a conversation manager, durable conversation records/reports, and model setup/settings are not implemented yet. Future database migrations, additional repositories, conversation data, and business rules belong in the Python backend, never in the frontend or native window layer.
