import { useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  CircleCheck,
  LoaderCircle,
  Sparkles,
} from "lucide-react";
import type {
  AIAction,
  AIJob,
  AIModelStatus,
  AIResult,
  LanguageChoice,
  Recording,
} from "@/lib/types";
import { languageName } from "@/lib/format";

const TABS: { id: AIAction; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "key_points", label: "Key Points" },
  { id: "action_items", label: "Action Items" },
  { id: "translation", label: "Translation" },
];

const LANGUAGES: Exclude<LanguageChoice, "auto">[] = ["uz", "ru", "en"];
const ACTIVE_STATUSES = ["queued", "downloading", "loading_model", "processing"];

export interface AITextPanelProps {
  recording: Recording;
  modelStatus: AIModelStatus | null;
  activeJob: AIJob | null;
  onRun: (
    recordingId: string,
    operation: AIAction,
    targetLanguage: Exclude<LanguageChoice, "auto"> | null,
  ) => Promise<void>;
}

export function AITextPanel({ recording, modelStatus, activeJob, onRun }: AITextPanelProps) {
  const [selectedTab, setSelectedTab] = useState<AIAction>("summary");
  const [targetLanguage, setTargetLanguage] = useState<Exclude<LanguageChoice, "auto">>("en");
  const result = recording.ai_results[selectedTab];
  const running = Boolean(activeJob && ACTIVE_STATUSES.includes(activeJob.status));
  const currentJob = activeJob?.recording_id === recording.id ? activeJob : null;
  const localModelOperation = currentJob?.operation === selectedTab;
  const supportedLanguage = LANGUAGES.some(
    (language) => language === recording.transcription?.language,
  );
  const canTranslate = Boolean(
    supportedLanguage &&
      recording.transcription &&
      targetLanguage !== recording.transcription.language,
  );
  const disabled = !recording.transcription || !supportedLanguage || running || (
    selectedTab === "translation" && !canTranslate
  );

  function runSelected() {
    if (disabled) return;
    void onRun(
      recording.id,
      selectedTab,
      selectedTab === "translation" ? targetLanguage : null,
    );
  }

  return (
    <section aria-label="Local AI tools" className="ai-panel">
      <div className="ai-panel-heading">
        <div>
          <div className="ai-panel-title"><Sparkles size={15} /><h2>AI text tools</h2></div>
          <p>Private processing on this device</p>
        </div>
        <span className={`ai-model-badge${modelStatus?.downloaded ? " ready" : ""}`}>
          <span />{modelStatus?.loaded ? "Model ready" : modelStatus?.downloaded ? "Model downloaded" : "Optional model"}
        </span>
      </div>

      <div aria-label="AI text operations" className="ai-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            aria-selected={selectedTab === tab.id}
            className={`ai-tab${selectedTab === tab.id ? " selected" : ""}`}
            key={tab.id}
            onClick={() => setSelectedTab(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
            {recording.ai_results[tab.id] && <Check aria-label="Generated" size={12} />}
          </button>
        ))}
      </div>

      {!recording.transcription ? (
        <div className="ai-empty-state">
          <Sparkles size={16} />
          <p>Transcribe this recording first to use local AI tools.</p>
        </div>
      ) : (
        <>
          {!modelStatus?.downloaded && !modelStatus?.loaded && (
            <div className="ai-model-note">
              <div className="ai-note-icon"><AlertCircle size={14} /></div>
              <p>
                Qwen3 1.7B Q4_K_M is optional. Its first AI task downloads about 1.1 GB;
                recordings remain available without it.
              </p>
            </div>
          )}

          {!supportedLanguage && (
            <div className="ai-model-note">
              <div className="ai-note-icon"><AlertCircle size={14} /></div>
              <p>Local AI text tools support Uzbek, Russian, and English transcripts.</p>
            </div>
          )}

          {running && (
            <div aria-live="polite" className="ai-progress">
              <div className="ai-progress-heading">
                <LoaderCircle className="spin" size={15} />
                <span>{currentJob?.message ?? "Another recording is using the local AI engine…"}</span>
                {currentJob && <strong>{Math.round(currentJob.progress)}%</strong>}
              </div>
              {currentJob && (
                <div className="ai-progress-track">
                  <span style={{ width: `${currentJob.progress}%` }} />
                </div>
              )}
            </div>
          )}

          {currentJob?.status === "failed" && (
            <div className="ai-error" role="alert">
              <AlertCircle size={14} />
              <span>{currentJob.error ?? "The local AI task failed."}</span>
            </div>
          )}

          {selectedTab === "translation" && (
            <label className="ai-language-select">
              <span>Translate into</span>
              <span className="ai-select-wrap">
                <select
                  aria-label="Translation target language"
                  onChange={(event) =>
                    setTargetLanguage(event.target.value as Exclude<LanguageChoice, "auto">)
                  }
                  value={targetLanguage}
                >
                  {LANGUAGES.map((language) => (
                    <option key={language} value={language}>{languageName(language)}</option>
                  ))}
                </select>
                <ChevronDown aria-hidden="true" size={13} />
              </span>
            </label>
          )}

          {result ? (
            <div aria-live="polite" className="ai-result">
              <div className="ai-result-meta">
                <CircleCheck size={13} />
                <span>{result.model}</span>
                {result.operation !== "translation" ? (
                  <span>{languageName(result.language)}</span>
                ) : (
                  <span>{languageName(result.source_language)} → {languageName(result.target_language)}</span>
                )}
              </div>
              <AIResultView result={result} />
              <p className="ai-accuracy-note">AI-generated text can be inaccurate. Review it before relying on it.</p>
            </div>
          ) : !running ? (
            <p className="ai-result-placeholder">
              {selectedTab === "translation"
                ? "Translate the transcript while keeping the original text unchanged."
                : "Generate a separate result from the original transcript."}
            </p>
          ) : null}

          <div className="ai-actions">
            <button
              className="ai-generate-button"
              disabled={disabled}
              onClick={runSelected}
              type="button"
            >
              {localModelOperation && running
                ? <LoaderCircle className="spin" size={14} />
                : <Sparkles size={14} />}
              {result ? "Regenerate" : "Generate"} {TABS.find((tab) => tab.id === selectedTab)?.label}
            </button>
            {modelStatus?.status === "failed" && (
              <span className="ai-model-error">{modelStatus.error}</span>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function AIResultView({ result }: { result: AIResult }) {
  switch (result.operation) {
    case "summary":
      return <p className="ai-summary-text">{result.summary}</p>;
    case "key_points":
      return <ul className="ai-list">{result.key_points.map((point, index) => <li key={`${index}-${point}`}>{point}</li>)}</ul>;
    case "action_items":
      return (
        <div className="ai-action-results">
          <h3>Action items</h3>
          {result.action_items.length ? (
            <ul className="ai-list">
              {result.action_items.map((item, index) => (
                <li key={`${index}-${item.task}`}>
                  <span>{item.task}</span>
                  {(item.owner || item.due) && (
                    <small>{[item.owner, item.due].filter(Boolean).join(" · ")}</small>
                  )}
                </li>
              ))}
            </ul>
          ) : <p className="ai-result-placeholder">No explicit action items found.</p>}
          <h3>Decisions</h3>
          {result.decisions.length ? (
            <ul className="ai-list">{result.decisions.map((decision, index) => <li key={`${index}-${decision}`}>{decision}</li>)}</ul>
          ) : <p className="ai-result-placeholder">No explicit decisions found.</p>}
        </div>
      );
    case "translation":
      return <p className="ai-translation-text">{result.translation}</p>;
  }
}
