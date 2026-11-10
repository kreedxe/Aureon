import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertCircle,
  AudioLines,
  Check,
  CircleStop,
  LoaderCircle,
  Mic,
  Phone,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react";
import {
  createConversation,
  getConversation,
  getConversationReadiness,
  installConversationModels,
} from "@/lib/api";
import { getBackendConfig } from "@/lib/tauri";
import type {
  ConversationReadiness,
  ConversationSummary,
  ConversationState,
  ConversationTranscript,
  LanguageChoice,
} from "@/lib/types";

interface ConversationEvent {
  type: "state" | "transcript" | "assistant" | "error" | "meter";
  state?: ConversationState;
  message?: string;
  text?: string;
  language?: Exclude<LanguageChoice, "auto">;
  language_probability?: number;
  level?: number;
}

const languageNames: Record<LanguageChoice, string> = {
  auto: "Auto detect",
  en: "English",
  ru: "Russian",
  uz: "Uzbek",
};

const stateLabels: Record<ConversationState, string> = {
  IDLE: "Ready to connect",
  INITIALIZING: "Preparing local models",
  GREETING: "Preparing greeting",
  LISTENING: "Listening",
  TRANSCRIBING: "Transcribing",
  THINKING: "Thinking",
  SPEAKING: "Speaking",
  INTERRUPTED: "Listening to you",
  ERROR: "Needs attention",
  ENDED: "Conversation ended",
};

interface ConversationWorkspaceProps {
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
  onConversationUpdated: () => void;
}

export function ConversationWorkspace({
  conversationId,
  onConversationCreated,
  onConversationUpdated,
}: ConversationWorkspaceProps) {
  const [readiness, setReadiness] = useState<ConversationReadiness | null>(null);
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const [state, setState] = useState<ConversationState>("IDLE");
  const [stateMessage, setStateMessage] = useState("");
  const [messages, setMessages] = useState<ConversationTranscript[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const [isInstalling, setIsInstalling] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isEnding, setIsEnding] = useState(false);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(conversationId);
  const [conversationTitle, setConversationTitle] = useState("New conversation");
  const [summary, setSummary] = useState<ConversationSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [isLoadingConversation, setIsLoadingConversation] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const captureRef = useRef<AudioWorkletNode | null>(null);
  const playbackRef = useRef<AudioBufferSourceNode | null>(null);
  const stateRef = useRef<ConversationState>("IDLE");
  const currentConversationIdRef = useRef<string | null>(conversationId);
  const loadedConversationIdRef = useRef<string | null | undefined>(undefined);
  const startingRef = useRef(false);
  const endingRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const lastMeterUpdateRef = useRef(0);

  const updateState = useCallback((nextState: ConversationState, message?: string) => {
    stateRef.current = nextState;
    setState(nextState);
    if (message) setStateMessage(message);
  }, []);

  const refreshReadiness = useCallback(async () => {
    try {
      setReadiness(await getConversationReadiness());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not check local model readiness.");
    }
  }, []);

  useEffect(() => {
    void refreshReadiness();
    const timer = window.setInterval(() => {
      if (readiness?.install_status === "running") void refreshReadiness();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [readiness?.install_status, refreshReadiness]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    if (loadedConversationIdRef.current === conversationId) return;
    loadedConversationIdRef.current = conversationId;
    currentConversationIdRef.current = conversationId;
    setCurrentConversationId(conversationId);
    setSummary(null);
    setSummaryError(null);
    setMessages([]);
    if (!conversationId) {
      setConversationTitle("New conversation");
      setStateMessage("");
      setIsLoadingConversation(false);
      updateState("IDLE");
      return;
    }

    let cancelled = false;
    setIsLoadingConversation(true);
    void getConversation(conversationId).then(
      (detail) => {
        if (cancelled || currentConversationIdRef.current !== conversationId) return;
        setConversationTitle(detail.title);
        setLanguage(detail.language);
        setSummary(detail.summary);
        setSummaryError(detail.summary_error);
        setMessages(
          detail.messages.map((message) => ({
            role: message.role,
            text: message.text,
            language: message.language,
            languageProbability: message.language_probability ?? undefined,
            timestamp: message.timestamp,
          })),
        );
        setIsLoadingConversation(false);
        updateState("ENDED", "Conversation ended.");
      },
      (reason: unknown) => {
        if (cancelled) return;
        setIsLoadingConversation(false);
        setError(
          reason instanceof Error ? reason.message : "Could not load the saved conversation.",
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, [conversationId, updateState]);

  const stopPlayback = useCallback(() => {
    const current = playbackRef.current;
    playbackRef.current = null;
    if (current) {
      current.onended = null;
      try {
        current.stop();
      } catch {
        // The source may have ended between an interruption and this stop.
      }
      current.disconnect();
    }
  }, []);

  const stopAudioCapture = useCallback(() => {
    captureRef.current?.port.close();
    captureRef.current?.disconnect();
    sourceRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    captureRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
    const context = contextRef.current;
    contextRef.current = null;
    if (context && context.state !== "closed") void context.close();
  }, []);

  const stopConversation = useCallback(() => {
    const socket = socketRef.current;
    endingRef.current = true;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "end" }));
    }
    setIsEnding(true);
    stopPlayback();
    stopAudioCapture();
  }, [stopAudioCapture, stopPlayback]);

  useEffect(
    () => () => {
      socketRef.current?.close(1000, "Conversation view closed");
      stopPlayback();
      stopAudioCapture();
    },
    [stopAudioCapture, stopPlayback],
  );

  const handleSocketEvent = useCallback(
    (event: MessageEvent<ArrayBuffer | string>) => {
      if (typeof event.data !== "string") {
        const context = contextRef.current;
        if (
          !context ||
          endingRef.current ||
          stateRef.current === "INTERRUPTED" ||
          stateRef.current === "ENDED"
        ) {
          return;
        }
        void context.decodeAudioData(event.data.slice(0)).then(
          (audio) => {
            if (
              contextRef.current !== context ||
              endingRef.current ||
              stateRef.current === "INTERRUPTED" ||
              stateRef.current === "ENDED"
            ) {
              return;
            }
            stopPlayback();
            const source = context.createBufferSource();
            source.buffer = audio;
            source.connect(context.destination);
            source.onended = () => {
              if (playbackRef.current !== source) return;
              playbackRef.current = null;
              const socket = socketRef.current;
              if (!endingRef.current && socket?.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "audio_finished" }));
              }
            };
            playbackRef.current = source;
            source.start();
          },
          (reason: unknown) => {
            setError(
              reason instanceof Error
                ? `Could not play local speech: ${reason.message}`
                : "Could not decode the local speech audio.",
            );
          },
        );
        return;
      }

      let message: ConversationEvent;
      try {
        message = JSON.parse(event.data) as ConversationEvent;
      } catch {
        setError("The local conversation returned an invalid event.");
        return;
      }
      if (message.type === "state" && message.state) {
        updateState(message.state, message.message);
        if (message.state === "ENDED") setIsEnding(false);
        if (message.state === "INTERRUPTED" || message.state === "ENDED") stopPlayback();
      } else if (message.type === "transcript" && message.text && message.language) {
        const transcriptText = message.text;
        setConversationTitle((current) =>
          current === "New conversation"
            ? transcriptText.length > 56
              ? `${transcriptText.slice(0, 53).trimEnd()}...`
              : transcriptText
            : current,
        );
        setMessages((current) => [
          ...current,
          {
            role: "user",
            text: transcriptText,
            language: message.language ?? "en",
            languageProbability: message.language_probability,
            timestamp: new Date().toISOString(),
          },
        ]);
        onConversationUpdated();
      } else if (message.type === "assistant" && message.text && message.language) {
        setMessages((current) => [
          ...current,
          {
            role: "assistant",
            text: message.text ?? "",
            language: message.language ?? "en",
            timestamp: new Date().toISOString(),
          },
        ]);
      } else if (message.type === "error" && message.message) {
        setError(message.message);
      } else if (message.type === "meter" && typeof message.level === "number") {
        setLevel(message.level);
      }
    },
    [onConversationUpdated, stopPlayback, updateState],
  );

  const startConversation = useCallback(async () => {
    if (startingRef.current || socketRef.current) return;
    startingRef.current = true;
    setIsStarting(true);
    setError(null);
    endingRef.current = false;
    setMessages([]);
    setLevel(0);
    setSummary(null);
    setSummaryError(null);
    updateState("INITIALIZING", "Requesting microphone access…");
    let socket: WebSocket | null = null;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
        throw new Error("Live microphone streaming is not available in this desktop runtime.");
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;
      const context = new AudioContext();
      contextRef.current = context;
      await context.resume();
      await context.audioWorklet.addModule("/pcm-capture-worklet.js");
      const input = context.createMediaStreamSource(stream);
      const capture = new AudioWorkletNode(context, "aureon-pcm-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      sourceRef.current = input;
      captureRef.current = capture;
      input.connect(capture);
      capture.connect(context.destination);

      const config = await getBackendConfig();
      const created = await createConversation(language);
      currentConversationIdRef.current = created.id;
      loadedConversationIdRef.current = created.id;
      setCurrentConversationId(created.id);
      setConversationTitle(created.title);
      onConversationCreated(created.id);
      const socketUrl = new URL("/api/v1/conversations/stream", config.baseUrl);
      socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(socketUrl);
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;
      socket.onopen = () => {
        socket?.send(
          JSON.stringify({
            type: "start",
            token: config.token,
            language,
            conversation_id: created.id,
          }),
        );
      };
      socket.onmessage = handleSocketEvent;
      socket.onerror = () => {
        setError("Could not connect to Aureon's local conversation service.");
      };
      socket.onclose = (event) => {
        if (socketRef.current === socket) socketRef.current = null;
        endingRef.current = false;
        stopPlayback();
        stopAudioCapture();
        setIsEnding(false);
        if (
          event.code !== 1000 &&
          stateRef.current !== "ERROR" &&
          stateRef.current !== "ENDED"
        ) {
          setError(event.reason || "The local conversation connection was closed.");
          updateState("ERROR", "The local conversation connection was closed.");
        } else if (stateRef.current !== "ERROR") {
          updateState("ENDED", "The microphone is off. This conversation has ended.");
        }
        onConversationUpdated();
        const savedId = currentConversationIdRef.current;
        if (savedId) {
          void getConversation(savedId).then(
            (detail) => {
              if (currentConversationIdRef.current !== savedId) return;
              setConversationTitle(detail.title);
              setSummary(detail.summary);
              setSummaryError(detail.summary_error);
              setMessages(
                detail.messages.map((message) => ({
                  role: message.role,
                  text: message.text,
                  language: message.language,
                  languageProbability: message.language_probability ?? undefined,
                  timestamp: message.timestamp,
                })),
              );
            },
            (reason: unknown) => {
              setError(
                reason instanceof Error ? reason.message : "Could not reload the saved conversation.",
              );
            },
          );
        }
      };
      capture.port.onmessage = ({ data }: MessageEvent<Float32Array>) => {
        if (
          socket?.readyState !== WebSocket.OPEN ||
          socket.bufferedAmount > 64 * 1024 ||
          !["LISTENING", "TRANSCRIBING", "THINKING", "SPEAKING", "INTERRUPTED"].includes(
            stateRef.current,
          )
        ) {
          return;
        }
        const monoSamples = data as Float32Array;
        const ratio = context.sampleRate / 16_000;
        const outputLength = Math.floor((monoSamples.length - 1) / ratio);
        if (outputLength <= 0) return;
        const pcm = new Int16Array(outputLength);
        let energy = 0;
        for (let index = 0; index < outputLength; index += 1) {
          const sourcePosition = index * ratio;
          const leftIndex = Math.floor(sourcePosition);
          const fraction = sourcePosition - leftIndex;
          const sample =
            monoSamples[leftIndex] * (1 - fraction) +
            monoSamples[Math.min(leftIndex + 1, monoSamples.length - 1)] * fraction;
          const clamped = Math.max(-1, Math.min(1, sample));
          pcm[index] = clamped < 0 ? clamped * 32768 : clamped * 32767;
          energy += clamped * clamped;
        }
        socket.send(pcm.buffer);
        const now = performance.now();
        if (now - lastMeterUpdateRef.current > 100) {
          setLevel(Math.min(1, Math.sqrt(energy / outputLength) * 4));
          lastMeterUpdateRef.current = now;
        }
      };
      updateState("INITIALIZING", "Connecting to the local voice assistant…");
    } catch (reason) {
      socket?.close();
      stopPlayback();
      stopAudioCapture();
      const errorName =
        reason instanceof DOMException ? reason.name : "";
      const detail =
        errorName === "NotAllowedError" || errorName === "SecurityError"
          ? "Microphone access was denied. Allow Aureon to use the microphone in system settings."
          : errorName === "NotFoundError"
            ? "No microphone was found. Connect a microphone and try again."
            : reason instanceof Error
              ? reason.message
              : "Could not start the local voice conversation.";
      setError(detail);
      updateState("ERROR", "The microphone or local audio pipeline could not start.");
    } finally {
      startingRef.current = false;
      setIsStarting(false);
    }
  }, [
    handleSocketEvent,
    language,
    onConversationCreated,
    stopAudioCapture,
    stopPlayback,
    updateState,
  ]);

  const prepareModels = useCallback(async () => {
    setError(null);
    setIsInstalling(true);
    try {
      setReadiness(await installConversationModels());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not prepare local models.");
    } finally {
      setIsInstalling(false);
      void refreshReadiness();
    }
  }, [refreshReadiness]);

  const isConnected =
    socketRef.current?.readyState === WebSocket.OPEN ||
    socketRef.current?.readyState === WebSocket.CONNECTING;
  const isActive = isConnected && state !== "ENDED";
  const canStart = Boolean(readiness?.ready) && !isConnected && !isStarting;
  const showSavedConversation = Boolean(currentConversationId && state === "ENDED");
  const availableLanguages = new Set(
    (readiness?.voices ?? []).map((voice) => voice.language.split(/[-_]/)[0].toLowerCase()),
  );

  return (
    <div className="conversation-workspace">
      <div className="conversation-heading">
        <div>
          <h1>{currentConversationId ? conversationTitle : "Talk to Aureon"}</h1>
        </div>
      </div>

      {error && (
        <div className="conversation-error" role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError(null)} type="button">×</button>
        </div>
      )}

      {!readiness?.ready && !currentConversationId ? (
        <section className="voice-setup-card">
          <div className="voice-setup-icon"><ShieldCheck size={20} /></div>
          <h2>Prepare voice models</h2>
          <p>First-time setup requires internet; conversations run offline.</p>
          <div className="voice-model-list">
            <ModelStatus label="Silero voice activity detection" ready={readiness?.vad_ready ?? false} />
            <ModelStatus label="Whisper speech recognition" ready={readiness?.whisper_ready ?? false} />
            <ModelStatus label="Qwen local conversation model" ready={readiness?.llm_ready ?? false} />
            <ModelStatus
              label="Installed English and Russian speech voices"
              ready={Boolean(
                availableLanguages.has("en") && availableLanguages.has("ru"),
              )}
            />
          </div>
          {readiness?.install_status === "running" && (
            <div className="voice-install-progress" aria-live="polite">
              <div className="voice-install-copy">
                <span>{readiness.install_message}</span>
                <span>{Math.round(readiness.install_progress)}%</span>
              </div>
              <div className="progress-track">
                <span style={{ width: `${readiness.install_progress}%` }} />
              </div>
            </div>
          )}
          {readiness?.install_error && (
            <p className="voice-install-error">{readiness.install_error}</p>
          )}
          <button
            className="voice-primary-button"
            disabled={isInstalling || readiness?.install_status === "running"}
            onClick={() => void prepareModels()}
            type="button"
          >
            {isInstalling || readiness?.install_status === "running" ? (
              <><LoaderCircle className="spin" size={16} /> Preparing local models…</>
            ) : readiness?.install_status === "failed" ? (
              <><RefreshCw size={15} /> Retry model setup</>
            ) : (
              <><WifiOff size={15} /> Download and prepare models</>
            )}
          </button>
        </section>
      ) : null}

      {readiness?.ready && !showSavedConversation ? (
        <>
          <section className={`conversation-stage ${isActive ? "conversation-stage-active" : ""}`}>
            <div className="conversation-stage-top">
              <span className={`conversation-state state-${state.toLowerCase()}`}>
                <span className={isActive ? "state-pulse" : "state-dot"} />
                {stateLabels[state]}
              </span>
              <label className="conversation-language">
                <span>Language</span>
                <select
                  disabled={isActive}
                  onChange={(event) => setLanguage(event.target.value as LanguageChoice)}
                  value={language}
                >
                  <option value="auto">Auto detect</option>
                  <option disabled={!availableLanguages.has("uz")} value="uz">Uzbek</option>
                  <option disabled={!availableLanguages.has("ru")} value="ru">Russian</option>
                  <option disabled={!availableLanguages.has("en")} value="en">English</option>
                </select>
              </label>
            </div>
            <div className={`conversation-orb ${isActive ? "orb-active" : ""} orb-${state.toLowerCase()}`}>
              <div className="conversation-orb-ring conversation-orb-ring-outer" />
              <div className="conversation-orb-ring conversation-orb-ring-inner" />
              <div className="conversation-orb-core">
                {isActive ? <AudioLines size={28} /> : <Mic size={27} />}
              </div>
            </div>
            <div className="conversation-state-copy" aria-live="polite">
              {stateMessage && <h2>{stateMessage}</h2>}
              {language === "auto" && !availableLanguages.has("uz") && (
                <p className="conversation-language-note">
                  Uzbek speech can be recognized, but no offline Uzbek voice is installed on this device.
                </p>
              )}
            </div>
            <div className="conversation-waveform" role="img" aria-label="Live microphone audio level">
              {Array.from({ length: 36 }, (_, index) => {
                const variation = 0.3 + ((index * 17) % 13) / 22;
                const height = isActive ? 5 + level * 43 * variation : 5 + (index % 4) * 2;
                return <span key={index} style={{ height: `${height}px` }} />;
              })}
            </div>
            <div className="conversation-controls">
              {isActive ? (
                <button
                  className="voice-end-button"
                  disabled={isEnding}
                  onClick={stopConversation}
                  type="button"
                >
                  <CircleStop size={16} /> {isEnding ? "Finishing…" : "End conversation"}
                </button>
              ) : (
                <button
                  className="voice-primary-button"
                  disabled={!canStart || Boolean(currentConversationId)}
                  onClick={() => void startConversation()}
                  type="button"
                >
                  <Phone size={15} />
                  {isStarting ? "Starting…" : "Start conversation"}
                </button>
              )}
            </div>
            <p className="conversation-privacy"><ShieldCheck size={13} /> Audio is not saved.</p>
          </section>
        </>
      ) : null}

      {summary && (
        <ConversationSummaryPanel summary={summary} />
      )}
      {summaryError && (
        <div className="conversation-error" role="status">
          <AlertCircle size={16} />
          <span>Summary unavailable: {summaryError}</span>
        </div>
      )}
      {isLoadingConversation ? (
        <div className="conversation-live-status"><LoaderCircle className="spin" size={14} /> Loading conversation…</div>
      ) : (
        <section className="conversation-transcript" aria-label="Conversation transcript">
          <div className="conversation-transcript-heading">
            <h2>{showSavedConversation ? "Transcript" : "Live transcript"}</h2>
            {messages.length > 0 && <span>{messages.length} messages</span>}
          </div>
          <div className="conversation-message-list">
            {messages.map((message, index) => (
              <article
                className={`conversation-message message-${message.role}`}
                key={`${message.timestamp ?? index}-${message.role}-${index}`}
              >
                <div className="conversation-message-meta">
                  <span>{message.role === "user" ? "You" : "Aureon"}</span>
                  <span>
                    {languageNames[message.language]}
                    {message.languageProbability === undefined
                      ? ""
                      : ` · ${Math.round(message.languageProbability * 100)}%`}
                  </span>
                </div>
                <p>{message.text}</p>
              </article>
            ))}
            {state === "TRANSCRIBING" && (
              <div className="conversation-live-status"><LoaderCircle className="spin" size={14} /> Transcribing…</div>
            )}
            {state === "THINKING" && (
              <div className="conversation-live-status"><LoaderCircle className="spin" size={14} /> Thinking…</div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </section>
      )}
    </div>
  );
}

function ConversationSummaryPanel({ summary }: { summary: ConversationSummary }) {
  return (
    <section className="conversation-summary" aria-label="Conversation summary">
      <h2>Summary</h2>
      <div className="conversation-summary-grid">
        <SummaryField label="Customer">
          <span>Name: {summary.customer_name}</span>
          <span>Age: {summary.customer_age}</span>
          <span>Location: {summary.customer_location}</span>
          <SummaryItems items={summary.other_customer_details} />
        </SummaryField>
        <SummaryField label="Interests">
          <SummaryItems items={summary.customer_interests} />
        </SummaryField>
        <SummaryField label="Needs">
          <SummaryItems items={summary.customer_needs} />
        </SummaryField>
        <SummaryField label="Purchase">
          <span>Intent: {summary.purchase_intent.replaceAll("_", " ")}</span>
          <span>Outcome: {summary.purchase_outcome.replaceAll("_", " ")}</span>
        </SummaryField>
        <SummaryField label="Tone">{summary.tone}</SummaryField>
        <SummaryField label="Important details">
          <SummaryItems items={summary.important_details} />
        </SummaryField>
        <SummaryField label="Next steps">
          <SummaryItems items={summary.next_steps} />
        </SummaryField>
      </div>
    </section>
  );
}

function SummaryField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="conversation-summary-field">
      <h3>{label}</h3>
      <div>{children}</div>
    </div>
  );
}

function SummaryItems({ items }: { items: string[] }) {
  return (
    <>
      {items.map((item, index) => (
        <span key={`${index}-${item}`}>{item}</span>
      ))}
    </>
  );
}

function ModelStatus({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className="voice-model-status">
      {ready ? <Check size={14} /> : <span className="voice-model-pending" />}
      <span>{label}</span>
      <strong>{ready ? "Ready" : "Needed"}</strong>
    </div>
  );
}
