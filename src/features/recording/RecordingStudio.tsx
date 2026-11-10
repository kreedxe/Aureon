import { useState } from "react";
import { AlertCircle, CircleStop, LoaderCircle, Mic, Pause, Play, RotateCcw, Trash2 } from "lucide-react";
import { LanguageSelect } from "@/components/ui/LanguageSelect";
import { Waveform } from "@/components/ui/Waveform";
import { formatDuration } from "@/lib/format";
import type { LanguageChoice } from "@/lib/types";
import { useRecorder } from "@/hooks/useRecorder";

export interface PendingAudio {
  blob: Blob;
  duration: number;
}

interface RecordingStudioProps {
  pendingAudio: PendingAudio | null;
  language: LanguageChoice;
  onLanguageChange: (language: LanguageChoice) => void;
  onSave: (blob: Blob, duration: number) => Promise<void>;
  onRetrySave: () => Promise<void>;
  onDiscardPending: () => void;
  onStatusChange: (status: ReturnType<typeof useRecorder>["status"]) => void;
}

export function RecordingStudio({
  pendingAudio,
  language,
  onLanguageChange,
  onSave,
  onRetrySave,
  onDiscardPending,
  onStatusChange,
}: RecordingStudioProps) {
  const [busy, setBusy] = useState(false);
  const recorder = useRecorder({ onSave, onStatusChange });
  const isActive = recorder.status === "recording" || recorder.status === "paused";

  async function retrySave() {
    setBusy(true);
    try {
      await onRetrySave();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="recording-studio">
      <div className="studio-topline">
        <LanguageSelect disabled={isActive || recorder.status === "saving"} onChange={onLanguageChange} value={language} />
      </div>

      <div className={`studio-hero${isActive ? " is-active" : ""}`}>
        <div className="studio-halo" />
        <div className="studio-time">{formatDuration(recorder.duration)}<span>{recorder.status === "paused" ? "PAUSED" : recorder.status === "saving" ? "SAVING" : isActive ? "RECORDING" : "READY"}</span></div>
        <div className="live-waveform"><Waveform analyser={recorder.analyser} /></div>
        <button
          aria-label={isActive ? "Recording in progress" : "Start recording"}
          className={`record-microphone${isActive ? " recording" : ""}`}
          disabled={recorder.status !== "idle" || Boolean(pendingAudio)}
          onClick={() => void recorder.start()}
          type="button"
        >
          {recorder.status === "saving" ? <LoaderCircle className="spin" size={25} /> : isActive ? <span className="microphone-live-dot" /> : <Mic size={25} strokeWidth={1.8} />}
        </button>
      </div>

      <div className="record-controls">
        {recorder.status === "recording" && (
          <>
            <button className="control-button pause-control" onClick={recorder.pause} type="button"><Pause size={15} fill="currentColor" />Pause</button>
            <button className="control-button stop-control" onClick={recorder.stop} type="button"><CircleStop size={16} />Finish recording</button>
          </>
        )}
        {recorder.status === "paused" && (
          <>
            <button className="control-button pause-control" onClick={recorder.resume} type="button"><Play size={15} fill="currentColor" />Resume</button>
            <button className="control-button stop-control" onClick={recorder.stop} type="button"><CircleStop size={16} />Finish recording</button>
          </>
        )}
      </div>

      {recorder.error && <div className="recorder-error" role="alert"><AlertCircle size={15} /><span>{recorder.error}</span></div>}
      {pendingAudio && (
        <div aria-live="polite" className="pending-save-card">
          <div className="pending-icon"><AlertCircle size={16} /></div>
          <div className="pending-copy"><strong>Recording is still here</strong><span>Couldn’t save it to this session. Try again or discard.</span></div>
          <button className="secondary-button" disabled={busy} onClick={() => void retrySave()} type="button">
            {busy ? <LoaderCircle className="spin" size={14} /> : <RotateCcw size={14} />}Retry
          </button>
          <button aria-label="Discard unsaved recording" className="icon-button" disabled={busy} onClick={onDiscardPending} type="button"><Trash2 size={14} /></button>
        </div>
      )}

      <div className="studio-assurance"><span>Session-only</span><span className="assurance-divider">·</span><span>Local transcription</span></div>
    </div>
  );
}
