import { useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Clipboard,
  FileAudio,
  Languages,
  LoaderCircle,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { LanguageSelect } from "@/components/ui/LanguageSelect";
import { Waveform } from "@/components/ui/Waveform";
import { AITextPanel, type AITextPanelProps } from "@/features/recordings/AITextPanel";
import { formatDuration, formatTimestamp, languageName } from "@/lib/format";
import type {
  AIJob,
  AIModelStatus,
  LanguageChoice,
  Recording,
  TranscriptionJob,
} from "@/lib/types";

interface RecordingDetailProps {
  recording: Recording;
  activeJob: TranscriptionJob | null;
  activeAIJob: AIJob | null;
  aiModelStatus: AIModelStatus | null;
  language: LanguageChoice;
  onLanguageChange: (language: LanguageChoice) => void;
  onTranscribe: (recordingId: string, language: LanguageChoice) => Promise<void>;
  onRunAI: AITextPanelProps["onRun"];
}

export function RecordingDetail({
  recording,
  activeJob,
  activeAIJob,
  aiModelStatus,
  language,
  onLanguageChange,
  onTranscribe,
  onRunAI,
}: RecordingDetailProps) {
  const [copied, setCopied] = useState(false);
  const [played, setPlayed] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const job = activeJob?.recording_id === recording.id ? activeJob : null;
  const isTranscribing = Boolean(job && ["queued", "loading_model", "transcribing"].includes(job.status));

  async function transcribe() {
    if (submitting || isTranscribing) return;
    setSubmitting(true);
    try {
      await onTranscribe(recording.id, language);
    } finally {
      setSubmitting(false);
    }
  }

  async function copyTranscript() {
    if (!recording.transcription) return;
    await navigator.clipboard.writeText(recording.transcription.text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <article className="recording-detail">
      <div className="detail-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" />VOICE MEMO</div>
          <h1>{recording.name}</h1>
          <div className="detail-metadata">
            <span>{formatTimestamp(recording.created_at)}</span>
            <span className="metadata-separator">·</span>
            <span>{formatDuration(recording.duration)}</span>
            {recording.transcription && (
              <>
                <span className="metadata-separator">·</span>
                <span>{languageName(recording.transcription.language)}</span>
              </>
            )}
          </div>
        </div>
        <div className="detail-art"><AudioLinesIcon /></div>
      </div>

      <section className="audio-card">
        <div className="audio-card-top">
          <div className="audio-title"><FileAudio size={15} /><span>Original recording</span></div>
          <span className="local-only"><span />Stored for this session</span>
        </div>
        <div className="audio-waveform">
          <Waveform progress={played} variant="playback" />
        </div>
        {recording.audioUrl ? (
          <audio
            aria-label={`Play ${recording.name}`}
            controls
            onTimeUpdate={(event) => {
              const audio = event.currentTarget;
              setPlayed(audio.duration ? audio.currentTime / audio.duration : 0);
            }}
            ref={audioRef}
            src={recording.audioUrl}
          />
        ) : (
          <p className="audio-unavailable">Audio playback is only available in the current app session.</p>
        )}
      </section>

      {isTranscribing ? (
        <section aria-live="polite" className="transcription-progress">
          <div className="progress-heading">
            <div className="progress-icon"><LoaderCircle className="spin" size={16} /></div>
            <div><h2>{job?.status === "loading_model" ? (job.message.toLowerCase().includes("downloading") ? "Downloading Whisper model" : "Getting the local model ready") : "Listening closely"}</h2><p>{job?.message}</p></div>
            <span className="progress-percent">{Math.round(job?.progress ?? 0)}%</span>
          </div>
          <div className="progress-track"><span style={{ width: `${job?.progress ?? 0}%` }} /></div>
          {job?.status === "loading_model" && (
            <p className="model-download-note">First use downloads the model once. After it is cached, transcription works offline.</p>
          )}
        </section>
      ) : recording.transcription ? (
        <section className="transcript-section">
          <div className="transcript-heading">
            <div><div className="transcript-title"><Sparkles size={15} /><h2>Transcript</h2></div>
              <p>{languageName(recording.transcription.language)} <span>·</span> {Math.round(recording.transcription.language_probability * 100)}% language confidence <span>·</span> Whisper {recording.transcription.model}</p>
            </div>
            <button className="secondary-button copy-button" onClick={() => void copyTranscript()} type="button">
              {copied ? <Check size={14} /> : <Clipboard size={14} />}{copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="transcript-body">{recording.transcription.text}</div>
        </section>
      ) : (
        <section className="transcript-empty">
          <div className="transcript-empty-mark"><Languages size={17} /></div>
          <div><h2>Words, kept in your language.</h2><p>Your recording will be transcribed privately on this device.</p></div>
        </section>
      )}

      <AITextPanel
        activeJob={activeAIJob}
        modelStatus={aiModelStatus}
        onRun={onRunAI}
        recording={recording}
      />

      <div className="transcription-actions">
        <LanguageSelect disabled={isTranscribing || submitting} onChange={onLanguageChange} value={language} />
        <Button
          className="transcribe-button"
          disabled={isTranscribing || submitting}
          onClick={() => void transcribe()}
          type="button"
        >
          {isTranscribing || submitting ? <LoaderCircle className="spin" size={15} /> :
            recording.transcription ? <RotateCcw size={15} /> : <Sparkles size={15} />}
          {recording.transcription ? "Transcribe again" : "Transcribe"}
          <ArrowUpRight className="transcribe-arrow" size={14} />
        </Button>
      </div>
      <p className="privacy-caption">Audio never leaves this device. Speech recognition is powered by Whisper running locally.</p>
    </article>
  );
}

function AudioLinesIcon() {
  return (
    <div className="detail-art-wave" aria-hidden="true">
      {Array.from({ length: 19 }, (_, index) => (
        <span key={index} style={{ height: `${18 + Math.abs(Math.sin(index * 0.79)) * 55}%` }} />
      ))}
    </div>
  );
}
