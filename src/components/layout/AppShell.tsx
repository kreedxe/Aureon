import { useMemo, useState } from "react";
import type { MouseEvent } from "react";
import {
  AudioLines,
  Check,
  Clock3,
  Mic,
  Moon,
  Pencil,
  Plus,
  Search,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import type { PropsWithChildren } from "react";
import type { Recording } from "@/lib/types";
import { formatDuration, formatRecordingDate } from "@/lib/format";

interface AppShellProps extends PropsWithChildren {
  recordings: Recording[];
  selectedId: string | null;
  error: string | null;
  isLight: boolean;
  onSelect: (id: string) => void;
  onNewRecording: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onToggleTheme: () => void;
  onDismissError: () => void;
}

export function AppShell({
  children,
  recordings,
  selectedId,
  error,
  isLight,
  onSelect,
  onNewRecording,
  onRename,
  onDelete,
  onToggleTheme,
  onDismissError,
}: AppShellProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => recordings.filter((recording) => recording.name.toLowerCase().includes(query.toLowerCase())),
    [recordings, query],
  );

  return (
    <div className={`aureon-window${isLight ? " theme-light" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><AudioLines aria-hidden="true" size={18} strokeWidth={2} /></div>
          <div className="brand-word">Aureon<span>Voice Studio</span></div>
        </div>

        <button className="new-recording" onClick={onNewRecording} type="button">
          <Plus aria-hidden="true" size={16} />
          <span>New recording</span>
          <Mic aria-hidden="true" className="new-recording-mic" size={15} />
        </button>

        <div className="library-heading">
          <span>Recordings</span>
          <span className="recording-count">{recordings.length}</span>
        </div>
        <label className="search-field">
          <Search aria-hidden="true" size={14} />
          <input
            aria-label="Search recordings"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search"
            value={query}
          />
          {query && (
            <button aria-label="Clear search" onClick={() => setQuery("")} type="button">
              <X size={13} />
            </button>
          )}
        </label>

        <div className="recording-list" role="list">
          {filtered.map((recording) => (
            <RecordingRow
              key={recording.id}
              onDelete={() => onDelete(recording.id)}
              onRename={(name) => onRename(recording.id, name)}
              onSelect={() => onSelect(recording.id)}
              recording={recording}
              selected={recording.id === selectedId}
            />
          ))}
          {filtered.length === 0 && (
            <p className="sidebar-empty">
              {recordings.length === 0 ? "Your recordings will appear here." : "No matching recordings."}
            </p>
          )}
        </div>

        <div className="sidebar-footer">
          <div className="local-badge"><span />On this device</div>
          <span className="sidebar-footer-note">Private by design</span>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-crumb"><span>Library</span><span className="crumb-slash">/</span><strong>{selectedId ? "Recording" : "Studio"}</strong></div>
          <div className="topbar-actions">
            <span className="topbar-local"><span />Local processing</span>
            <button
              aria-label={isLight ? "Switch to dark appearance" : "Switch to light appearance"}
              className="icon-button theme-toggle"
              onClick={onToggleTheme}
              title={isLight ? "Dark appearance" : "Light appearance"}
              type="button"
            >
              {isLight ? <Moon size={16} /> : <Sun size={16} />}
            </button>
          </div>
        </header>
        {error && (
          <div className="app-alert" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={onDismissError} type="button"><X size={14} /></button>
          </div>
        )}
        <section className="content-area">{children}</section>
      </main>
    </div>
  );
}

interface RecordingRowProps {
  recording: Recording;
  selected: boolean;
  onSelect: () => void;
  onRename: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
}

function RecordingRow({ recording, selected, onSelect, onRename, onDelete }: RecordingRowProps) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(recording.name);
  const [busy, setBusy] = useState(false);

  async function saveName() {
    const trimmed = name.trim();
    if (!trimmed || trimmed === recording.name || busy) {
      setName(recording.name);
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await onRename(trimmed);
      setEditing(false);
    } catch {
      setName(recording.name);
    } finally {
      setBusy(false);
    }
  }

  async function remove(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      await onDelete();
    } catch {
      // The application shell displays the operation error.
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      aria-current={selected ? "true" : undefined}
      className={`recording-row${selected ? " selected" : ""}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect();
      }}
      role="listitem"
      tabIndex={0}
    >
      <div className="recording-row-icon"><AudioLines aria-hidden="true" size={15} /></div>
      <div className="recording-row-copy">
        {editing ? (
          <input
            aria-label="Recording name"
            autoFocus
            maxLength={120}
            onBlur={() => void saveName()}
            onChange={(event) => setName(event.target.value)}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Enter") void saveName();
              if (event.key === "Escape") {
                setName(recording.name);
                setEditing(false);
              }
            }}
            value={name}
          />
        ) : (
          <span className="recording-row-name" title={recording.name}>{recording.name}</span>
        )}
        <span className="recording-row-meta">
          {recording.transcription_status === "completed" ? <Check size={11} /> :
            recording.transcription_status === "queued" || recording.transcription_status === "loading_model" || recording.transcription_status === "transcribing" ? <span className="mini-spinner" /> :
              recording.transcription_status === "failed" ? <X size={11} /> : <Clock3 size={11} />}
          {recording.transcription_status === "completed" ? "Transcribed" :
            recording.transcription_status === "failed" ? "Needs retry" :
              recording.transcription_status === "queued" ? "Queued" :
                recording.transcription_status === "loading_model" || recording.transcription_status === "transcribing" ? "Transcribing" :
                formatRecordingDate(recording.created_at)}
          <span className="row-dot">·</span>{formatDuration(recording.duration)}
        </span>
      </div>
      <div className="recording-row-actions">
        <button
          aria-label={`Rename ${recording.name}`}
          className="row-action"
          onClick={(event) => {
            event.stopPropagation();
            setName(recording.name);
            setEditing(true);
          }}
          type="button"
        >
          <Pencil size={12} />
        </button>
        <button
          aria-label={`Delete ${recording.name}`}
          className="row-action delete-action"
          disabled={busy}
          onClick={(event) => void remove(event)}
          type="button"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}
