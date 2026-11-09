import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderStatus = "idle" | "recording" | "paused" | "saving";

interface UseRecorderOptions {
  onSave: (blob: Blob, duration: number) => Promise<void>;
  onStatusChange?: (status: RecorderStatus) => void;
}

function microphoneError(error: unknown): string {
  if (!(error instanceof DOMException)) return "Could not start recording. Please try again.";
  if (error.name === "NotAllowedError" || error.name === "SecurityError") {
    return "Microphone access was denied. Allow Aureon to use the microphone in your system privacy settings.";
  }
  if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
    return "No microphone was found. Connect a microphone and try again.";
  }
  if (error.name === "NotReadableError" || error.name === "TrackStartError") {
    return "The microphone is busy or unavailable. Close other apps using it and try again.";
  }
  return `Could not access the microphone (${error.name}).`;
}

function getRecorderOptions(): MediaRecorderOptions | undefined {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/wav",
  ];
  const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  return mimeType ? { mimeType, audioBitsPerSecond: 128_000 } : undefined;
}

export function useRecorder({ onSave, onStatusChange }: UseRecorderOptions) {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const elapsedBeforePauseRef = useRef(0);
  const latestDurationRef = useRef(0);
  const onSaveRef = useRef(onSave);
  const onStatusChangeRef = useRef(onStatusChange);
  onSaveRef.current = onSave;
  onStatusChangeRef.current = onStatusChange;

  const updateStatus = useCallback((next: RecorderStatus) => {
    setStatus(next);
    onStatusChangeRef.current?.(next);
  }, []);

  const releaseAudio = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== "closed") void context.close();
    setAnalyser(null);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Microphone recording is not supported by this desktop webview.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      streamRef.current = stream;
      const options = getRecorderOptions();
      const recorder = options ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      elapsedBeforePauseRef.current = 0;
      latestDurationRef.current = 0;

      const context = new AudioContext();
      audioContextRef.current = context;
      const source = context.createMediaStreamSource(stream);
      const analyserNode = context.createAnalyser();
      analyserNode.fftSize = 128;
      source.connect(analyserNode);
      setAnalyser(analyserNode);
      await context.resume();

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      });
      recorder.addEventListener("error", () => {
        setError("The browser could not encode this recording. Try another microphone.");
      });
      recorder.addEventListener(
        "stop",
        async () => {
          const blob = new Blob(chunksRef.current, {
            type: recorder.mimeType || "audio/webm",
          });
          releaseAudio();
          updateStatus("saving");
          try {
            if (blob.size === 0) throw new Error("The recording was empty. Try recording again.");
            await onSaveRef.current(blob, latestDurationRef.current);
            setError(null);
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : String(reason));
          } finally {
            updateStatus("idle");
          }
        },
        { once: true },
      );
      startedAtRef.current = Date.now();
      recorder.start(500);
      updateStatus("recording");
    } catch (reason) {
      releaseAudio();
      setError(microphoneError(reason));
      updateStatus("idle");
    }
  }, [releaseAudio, updateStatus]);

  const pause = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    elapsedBeforePauseRef.current += Date.now() - startedAtRef.current;
    latestDurationRef.current = elapsedBeforePauseRef.current / 1000;
    recorder.pause();
    updateStatus("paused");
  }, [updateStatus]);

  const resume = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "paused") return;
    startedAtRef.current = Date.now();
    recorder.resume();
    updateStatus("recording");
  }, [updateStatus]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    if (recorder.state === "recording") {
      elapsedBeforePauseRef.current += Date.now() - startedAtRef.current;
    }
    latestDurationRef.current = elapsedBeforePauseRef.current / 1000;
    setDuration(Math.floor(latestDurationRef.current));
    recorder.stop();
  }, []);

  useEffect(() => {
    if (status !== "recording") return;
    const timer = window.setInterval(() => {
      const total = elapsedBeforePauseRef.current + Date.now() - startedAtRef.current;
      latestDurationRef.current = total / 1000;
      setDuration(Math.floor(total / 1000));
    }, 100);
    return () => window.clearInterval(timer);
  }, [status]);

  useEffect(
    () => () => {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      releaseAudio();
    },
    [releaseAudio],
  );

  return { status, duration, error, analyser, start, pause, resume, stop, clearError: () => setError(null) };
}
