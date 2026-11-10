![Aureon banner](banner.jpg)


Aureon is a local-first desktop shop assistant. Its Voice Studio supports continuous, on-device conversations; the product catalog is managed in a separate workspace. Product records, conversation transcripts, and generated conversation summaries persist in SQLite. Microphone audio remains in memory only.

## Architecture

- **React and TypeScript** provide the live conversation controls, session recording library, product management, playback, and transcript display. An `AudioWorklet` converts microphone input to PCM frames and streams them over an authenticated loopback WebSocket; it contains no speech recognition or catalog logic.
- **FastAPI and Python** run Silero voice activity detection, faster-whisper transcription, the local Qwen conversation manager, SQLite history/catalog access, and local speech synthesis. Conversation audio is streamed in memory and is not saved.
- **Rust and Tauri** start and supervise the backend, generate a per-launch session token and loopback port, wait for authenticated readiness, and stop the backend when the desktop app exits.

See [docs/architecture.md](docs/architecture.md) for request flow and security boundaries.

## Technology

- Tauri 2, Rust, and Cargo.
- React, strict TypeScript, Vite, Tailwind CSS, shadcn-style local components, Lucide React.
- FastAPI, Pydantic, Uvicorn, HTTPX, faster-whisper, ONNX Runtime, NumPy, SQLite, and uv.
- Optional local AI text tools use llama-cpp-python with Qwen3 1.7B Instruct GGUF Q4_K_M.
- `pnpm` for frontend dependencies; `uv` and `backend/pyproject.toml` for Python dependencies.

## Directory structure

```text
src/                         React presentation, recording hooks, API client
  app/                       Application composition
  components/layout/         Desktop sidebar and library
  components/ui/             Reusable controls, language selector, waveform
  features/conversation/     Live voice conversation
  features/recording/        Session recording tools
  features/recordings/       Recording detail and empty state
  features/products/         Local product catalog and editor
  hooks/                     Recorder and library UI state
  lib/                       API client, types, formatting, Tauri IPC
  styles/                    Tailwind theme and global styles
src-tauri/                   Rust lifecycle manager and Tauri configuration
  capabilities/              Least-privilege webview permissions
  src/                       Application entry point, commands, backend manager
backend/                     Independent Python API and local conversation services
  app/api/routes/            Conversation, product, recording, and transcription endpoints
  app/core/                  Configuration and authentication
  app/schemas/               Pydantic request/response models
  app/services/              SQLite catalog, session storage, and local inference
  tests/                      Product, API, and recording workflow tests
docs/                        Architecture documentation
scripts/                     Development helpers
```

## Prerequisites

Install Node.js 22.12+ or 24 LTS, pnpm 10+, Rust stable (including Cargo), and uv. Python 3.12 or newer is managed by uv if it is not already available.

Tauri system prerequisites vary by platform; see the [official Tauri prerequisites](https://v2.tauri.app/start/prerequisites/):

- **macOS:** Xcode or Xcode Command Line Tools and CMake. Microphone permission is requested by the operating system.
- **Windows 10/11:** Microsoft C++ Build Tools with Desktop development with C++, CMake, and Microsoft Edge WebView2 Runtime. Verify microphone privacy settings.
- **Linux:** distribution-specific GTK/WebKitGTK 4.1, CMake, a C++ compiler, and build dependencies. Debian/Ubuntu packages documented by Tauri include `libwebkit2gtk-4.1-dev`, `build-essential`, `cmake`, `curl`, `wget`, `file`, `libxdo-dev`, `libssl-dev`, `libayatana-appindicator3-dev`, and `librsvg2-dev`. Install `espeak-ng` and local `en`/`ru` voices for offline speech output; the host audio stack and microphone permissions must also be configured.
- **Windows:** the built-in `System.Speech` voice engine is used; local English and Russian voices must be installed in Windows speech settings.
- **macOS:** the built-in `say` and `afconvert` tools are used; local English and Russian voices must be installed in macOS settings.

`uv sync` builds `llama-cpp-python` with CMake and the platform C++ toolchain when no compatible wheel is available.

The application targets macOS (Apple Silicon and Intel), Windows, and Linux, but target builds and microphone behavior must be verified on each host. Cross-platform compatibility is not claimed as certified.

## Install

From the repository root:

```sh
pnpm install
uv sync --project backend
```

The first install can download a uv-managed Python interpreter and frontend/backend packages.

## Development

Start the complete desktop application with one command:

```sh
pnpm dev
```

Vite provides HMR. Tauri starts the native window; Rust launches Uvicorn through uv in reload mode and supervises its lifecycle. The microphone is accessed using `getUserMedia` and an `AudioWorklet`. If permission is denied or no input device is available, the studio displays an error.

The backend binds only to `127.0.0.1`. Rust chooses the port and creates a random token for the application session. The frontend obtains both through the narrow `get_backend_config` Tauri command; neither URL nor secret is hardcoded in the frontend.

## Live local voice conversations

The Voice Studio pipeline is:

```text
Microphone → PCM WebSocket → Silero VAD → faster-whisper → local conversation manager
           → Qwen product-search plan → SQLite product lookup → Qwen response → OS local TTS → speaker
```

The worklet resamples microphone audio to mono 16 kHz PCM. Python buffers 512-sample frames for Silero VAD, ends a turn after approximately 640 ms of silence, and transcribes the completed utterance once with faster-whisper `small`. The selected language is passed to Whisper; Auto uses Whisper's detected language. The transcript and detected language are returned to the UI. Partial word-level transcription is not currently streamed.

The local Qwen model uses a bounded context window hydrated from the saved conversation history. It creates a validated product-search plan only when the customer actually asks about the catalog. Python executes that search against SQLite. Exact prices and stock counts come from database records, not the model. A no-match explanation is included only for a relevant failed lookup.

Speech synthesis uses the operating system's installed offline voices: macOS `say`/`afconvert`, Windows `System.Speech`, or Linux `espeak-ng`. English and Russian voices are required to enable conversations. Uzbek transcription is supported, but spoken Uzbek requires an installed Uzbek system voice. When Auto detects a language without a local voice, Aureon reports that limitation rather than speaking with a different language voice.

To prepare for offline use, open Voice Studio and choose **Download and prepare models** while internet access is available. This setup action downloads or verifies faster-whisper `small`, Qwen3 1.7B Q4_K_M, and the Silero ONNX model, and loads them locally. Model files are cached under the OS user cache (`Aureon/whisper`, `Aureon/qwen`, and `Aureon/voice`). Expect about 1.6 GB for model files, plus cache/runtime overhead; the Qwen model also needs RAM for its weights and context. After setup completes, conversation requests use local inference and do not call the network. A missing model prevents the session from starting; the conversation path uses cache-only model loading.

During a session the frontend sends an unpredictable per-launch token in its WebSocket start frame. Rust supplies that token to the UI using Tauri IPC; the backend still binds only to loopback. Audio frames are withheld until the greeting finishes and the backend reports `LISTENING`, preventing startup audio from becoming a duplicate turn. Silero detection continues while the assistant speaks. On a speech interruption, Python changes the exposed state to `INTERRUPTED` and the UI stops the current audio source. Every conversation has a unique ID; messages, timestamps, language, title, completion state, and a structured local-LLM summary are stored in SQLite. The user can reopen or explicitly delete individual conversations. Only microphone PCM remains temporary.

## Local product catalog

Select **Products** in the sidebar to create, edit, search, filter, sort, and delete catalog entries. Product names, descriptions, exact decimal prices, three-letter currency codes, stock counts, availability, category, optional brand, specifications, and timestamps are validated in Python and stored in a local SQLite database. Zero stock is reported as out of stock; discontinued listings remain distinct. All reads and writes go through the authenticated FastAPI API; React does not access SQLite.

The product editor can optionally draft a description using the local Qwen model. The generator receives only product name, price/currency, category, brand, and supplied specifications; it does not save product data. The draft is inserted into the editable description field and explicitly marked for human review before the owner saves it. Model setup can require the documented first-use download; catalog CRUD works without the model.

The database is created on first launch using the OS application-data directory through `platformdirs` (for example, `~/Library/Application Support/Aureon/Aureon/aureon.sqlite3` on macOS, `%LOCALAPPDATA%\\Aureon\\Aureon\\aureon.sqlite3` on Windows, and `~/.local/share/Aureon/aureon.sqlite3` on Linux). Product records persist across app sessions and stay on this device. The SQLite runtime is part of Python's standard library; no extra database package is needed.

## Local transcription and privacy

The API accepts audio uploads, stores them under an OS temporary directory unique to the active backend session, and removes that directory when the service shuts down. Recordings are not stored in a database or retained across application sessions. Audio playback is supplied by the frontend's in-memory object URLs.

Transcription uses the multilingual faster-whisper `small` model with CPU int8 inference. It supports Auto detection and Uzbek (`uz`), Russian (`ru`), and English (`en`). It transcribes the original language; it does not translate. Job progress, detected language, and language probability are returned by the API. First-use model download reports transferred bytes and progress in the UI; model loading and audio transcription have separate progress stages. Only one transcription can run at a time; requests while busy receive a clear conflict response. The model loads lazily on the first transcription and is cached in the user's OS cache directory for later launches. Its first download requires internet access; after it is cached, inference is local and can run offline. There is no cloud transcription fallback.

The exact audio container/codec support depends on formats accepted by the installed faster-whisper/FFmpeg stack; unsupported or corrupt audio returns an error rather than a cloud fallback. Model download size and inference speed depend on the machine. CPU inference may be slow for long recordings.

## Optional local AI text tools

After a transcript is available, the recording detail panel can generate a summary, key points, action items and decisions, or a translation to Uzbek, Russian, or English. Each operation runs asynchronously in Python and validates its JSON result with Pydantic. Results are stored separately from the original transcript in the current session; re-running an operation replaces only that operation's AI result. Summary, key points, and action extraction preserve the transcript's language. Translation changes language only when explicitly selected.

The default model is **Qwen3 1.7B Instruct, GGUF Q4_K_M** from `unsloth/Qwen3-1.7B-GGUF` (about 1.1 GB). The model is optional and is not downloaded at startup. The first AI request downloads it from Hugging Face and requires internet access; the model is then cached and reused for later app sessions. After caching, inference is local and can work offline. Transcripts and generated results are never sent to an external API; there is no cloud inference fallback. Outputs from a small language model can be inaccurate and should be reviewed, especially translations.

The persistent cache is managed by `platformdirs` and is separate from temporary recordings. Typical locations are `~/Library/Caches/Aureon/Aureon/qwen` on macOS, `%LOCALAPPDATA%\\Aureon\\Aureon\\Cache\\qwen` on Windows, and `~/.cache/Aureon/qwen` on Linux. Ensure roughly 1.1 GB of free storage for the model plus additional space for the Hugging Face cache/runtime. llama.cpp inference requires additional available RAM for model weights and context; 4 GB or more of available memory is a practical minimum, and more memory improves headroom. The current implementation uses CPU inference; long transcripts or lower-powered machines may take longer. If the model is not installed, recording and transcription remain available without AI features.

## Test and type check

```sh
uv run --directory backend pytest
uv run --project backend ruff check backend/app backend/tests
pnpm typecheck
pnpm build
```

Conversation unit tests validate state/message handling and product-price/stock grounding against a temporary SQLite database. AI behavior tests use a fake local model so they validate the four structured result types for Uzbek, Russian, and English without downloading the model. Physical microphone, interruption, and speaker behavior must be verified on each host with its actual audio devices.

## Production builds

Build the frontend with `pnpm build`, or invoke the desktop bundle build with:

```sh
pnpm build:desktop
```

Tauri is configured for macOS `.app`/`.dmg`, Windows NSIS installer, and Linux AppImage/`.deb`. Build each target on its supported host/toolchain; cross-compilation has platform-specific constraints. Signing and release CI have not been configured or tested.

The macOS Apple Silicon `.app` and `.dmg` bundle build has been verified. This verifies packaging, not a fully runnable release: the release backend launcher still requires the packaged Python sidecar described below. Windows and Linux builds have not been tested.

**Important:** The Rust release-mode backend launcher intentionally reports an error until a packaged Python executable is supplied. Development runs use uv-managed Python and are functional. A distributable installer requires a target-specific PyInstaller executable bundled as a Tauri sidecar/resource. This packaging work and Windows/Linux release builds remain unfinished.

## Add functionality

### Add an API endpoint

1. Define validated request/response models in `backend/app/schemas`.
2. Put application behavior in `backend/app/services`.
3. Add a typed route in `backend/app/api/routes` and register it in `backend/app/main.py`.
4. Add API tests in `backend/tests` and run the test commands above.

AI operations follow the same split: add or refine the Pydantic result schema in `backend/app/schemas/ai.py`, inference prompt/validation in `backend/app/services/ai_engine.py`, then expose it through the recording AI job route. Keep inference local and return validated, structured results.

### Add a frontend feature

1. Add presentation components under `src/features/<feature>` and reusable controls under `src/components/ui`.
2. Add HTTP calls/types in `src/lib`; use hooks to connect asynchronous API state to the UI.
3. Compose the feature in `src/app/App.tsx` or the layout. Keep business logic and persistence in Python.

## Next sales-assistant stages and packaging

Conversation transcripts and structured summaries persist in SQLite; microphone audio remains temporary. An Uzbek offline voice is not installed on this macOS host. Physical audio-device behavior and Windows/Linux runtime builds require testing on those platforms before compatibility can be certified.

For distribution, package the backend and model-loading dependencies as a target-specific PyInstaller executable, configure it as a Tauri sidecar/resource, and validate startup, readiness, error reporting, cleanup, permissions, and shutdown on each supported OS. Models are downloaded on first use and cached separately; they are not currently bundled into the application installer.
