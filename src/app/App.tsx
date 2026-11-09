import { useCallback, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyLibrary } from "@/features/recordings/EmptyLibrary";
import { RecordingDetail } from "@/features/recordings/RecordingDetail";
import { RecordingStudio, type PendingAudio } from "@/features/recording/RecordingStudio";
import { useRecordingLibrary } from "@/hooks/useRecordingLibrary";
import type { RecorderStatus } from "@/hooks/useRecorder";
import type { LanguageChoice } from "@/lib/types";

export function App() {
  const library = useRecordingLibrary();
  const [studioVisible, setStudioVisible] = useState(false);
  const [isLight, setIsLight] = useState(false);
  const [pendingAudio, setPendingAudio] = useState<PendingAudio | null>(null);
  const [recorderStatus, setRecorderStatus] = useState<RecorderStatus>("idle");
  const [language, setLanguage] = useState<LanguageChoice>("auto");

  const saveRecording = useCallback(async (blob: Blob, duration: number) => {
    setPendingAudio({ blob, duration });
    const now = new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date());
    await library.addRecording(blob, duration, `Recording · ${now}`);
    setPendingAudio(null);
    setStudioVisible(false);
  }, [library.addRecording]);

  const retrySave = useCallback(async () => {
    if (!pendingAudio) return;
    await saveRecording(pendingAudio.blob, pendingAudio.duration);
  }, [pendingAudio, saveRecording]);

  const transcribe = useCallback(
    (recordingId: string, language: LanguageChoice) => library.transcribe(recordingId, language),
    [library.transcribe],
  );

  return (
    <AppShell
      error={library.error}
      isLight={isLight}
      onDelete={library.remove}
      onDismissError={library.clearError}
      onNewRecording={() => setStudioVisible(true)}
      onRename={library.rename}
      onSelect={(id) => {
        library.setSelectedId(id);
        if (recorderStatus === "idle") setStudioVisible(false);
      }}
      onToggleTheme={() => setIsLight((current) => !current)}
      recordings={library.recordings}
      selectedId={library.selectedId}
    >
      {studioVisible ? (
        <RecordingStudio
          language={language}
          onLanguageChange={setLanguage}
          onDiscardPending={() => setPendingAudio(null)}
          onRetrySave={retrySave}
          onSave={saveRecording}
          onStatusChange={setRecorderStatus}
          pendingAudio={pendingAudio}
        />
      ) : library.selectedRecording ? (
        <RecordingDetail
          activeAIJob={library.activeAIJob}
          activeJob={library.activeJob}
          aiModelStatus={library.aiModelStatus}
          language={language}
          onLanguageChange={setLanguage}
          onRunAI={library.runAI}
          onTranscribe={transcribe}
          recording={library.selectedRecording}
        />
      ) : (
        <EmptyLibrary isLoading={library.isLoading} onNewRecording={() => setStudioVisible(true)} />
      )}
    </AppShell>
  );
}
