import { useCallback, useEffect, useRef, useState } from "react";
import {
  beginAIJob,
  beginTranscription,
  deleteRecording as deleteRecordingRequest,
  getAIJob,
  getAIModelStatus,
  getTranscriptionJob,
  listRecordings,
  renameRecording as renameRecordingRequest,
  uploadRecording,
} from "@/lib/api";
import type {
  AIAction,
  AIJob,
  AIModelStatus,
  LanguageChoice,
  Recording,
  TranscriptionJob,
} from "@/lib/types";

function toRecording(recording: Omit<Recording, "audioUrl">, audioUrl: string | null = null): Recording {
  return { ...recording, audioUrl };
}

export function useRecordingLibrary() {
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<TranscriptionJob | null>(null);
  const [activeAIJob, setActiveAIJob] = useState<AIJob | null>(null);
  const [aiModelStatus, setAIModelStatus] = useState<AIModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const objectUrls = useRef(new Set<string>());
  const mounted = useRef(true);

  const selectedRecording = recordings.find((item) => item.id === selectedId) ?? null;

  useEffect(() => {
    mounted.current = true;
    void listRecordings()
      .then(({ recordings: items }) => {
        if (mounted.current) setRecordings(items.map((item) => toRecording(item)));
      })
      .catch((reason: unknown) => {
        if (mounted.current) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (mounted.current) setIsLoading(false);
      });
    return () => {
      mounted.current = false;
      for (const url of objectUrls.current) URL.revokeObjectURL(url);
    };
  }, []);

  useEffect(() => {
    void getAIModelStatus()
      .then((status) => {
        if (mounted.current) setAIModelStatus(status);
      })
      .catch((reason: unknown) => {
        if (mounted.current) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
  }, []);

  const addRecording = useCallback(async (blob: Blob, duration: number, name: string) => {
    const audioUrl = URL.createObjectURL(blob);
    objectUrls.current.add(audioUrl);
    try {
      const recording = await uploadRecording(blob, name, duration);
      if (!mounted.current) return null;
      const item = toRecording(recording, audioUrl);
      setRecordings((current) => [item, ...current]);
      setSelectedId(item.id);
      setError(null);
      return item;
    } catch (reason) {
      URL.revokeObjectURL(audioUrl);
      objectUrls.current.delete(audioUrl);
      throw reason;
    }
  }, []);

  const rename = useCallback(async (recordingId: string, name: string) => {
    try {
      const updated = await renameRecordingRequest(recordingId, name);
      setRecordings((current) =>
        current.map((item) =>
          item.id === recordingId ? toRecording(updated, item.audioUrl) : item,
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      throw reason;
    }
  }, []);

  const remove = useCallback(async (recordingId: string) => {
    try {
      await deleteRecordingRequest(recordingId);
      setRecordings((current) => {
        const item = current.find((recording) => recording.id === recordingId);
        if (item?.audioUrl) {
          URL.revokeObjectURL(item.audioUrl);
          objectUrls.current.delete(item.audioUrl);
        }
        return current.filter((recording) => recording.id !== recordingId);
      });
      setSelectedId((current) => (current === recordingId ? null : current));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      throw reason;
    }
  }, []);

  const transcribe = useCallback(async (recordingId: string, language: LanguageChoice) => {
    setError(null);
    let started = false;
    let failed = false;
    try {
      const { job_id: jobId } = await beginTranscription(recordingId, language);
      started = true;
      setRecordings((current) =>
        current.map((item) =>
          item.id === recordingId ? { ...item, transcription_status: "queued" } : item,
        ),
      );
      let job: TranscriptionJob;
      do {
        job = await getTranscriptionJob(jobId);
        if (mounted.current) setActiveJob(job);
        if (mounted.current) {
          setRecordings((current) =>
            current.map((item) =>
              item.id === recordingId
                ? { ...item, transcription_status: job.status }
                : item,
            ),
          );
        }
        if (job.status === "failed") {
          failed = true;
          throw new Error(job.error ?? "Transcription failed.");
        }
        if (job.status === "completed") break;
        await new Promise((resolve) => window.setTimeout(resolve, 650));
      } while (mounted.current);

      if (!mounted.current) return;
      if (job.transcription) {
        setRecordings((current) =>
          current.map((item) =>
            item.id === recordingId
              ? {
                  ...item,
                  transcription: job.transcription,
                  transcription_status: "completed",
                  ai_results: {},
                }
              : item,
          ),
        );
      }
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      if (mounted.current) setError(message);
      if (started && failed) {
        if (mounted.current) {
          setRecordings((current) =>
            current.map((item) =>
              item.id === recordingId ? { ...item, transcription_status: "failed" } : item,
            ),
          );
        }
      }
    } finally {
      if (mounted.current) setActiveJob(null);
    }
  }, []);

  const runAI = useCallback(async (
    recordingId: string,
    operation: AIAction,
    targetLanguage: Exclude<LanguageChoice, "auto"> | null,
  ) => {
    setError(null);
    try {
      const initialJob = await beginAIJob(recordingId, operation, targetLanguage);
      if (mounted.current) setActiveAIJob(initialJob);
      let job = initialJob;
      while (mounted.current && !["completed", "failed"].includes(job.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 700));
        job = await getAIJob(initialJob.id);
        if (mounted.current) setActiveAIJob(job);
      }

      if (!mounted.current) return;
      if (job.status === "failed") {
        setError(job.error ?? "The local AI task failed.");
        return;
      }
      if (job.result) {
        setRecordings((current) =>
          current.map((item) =>
            item.id === recordingId
              ? {
                  ...item,
                  ai_results: {
                    ...item.ai_results,
                    [operation]: job.result,
                  },
                }
              : item,
          ),
        );
        const status = await getAIModelStatus();
        if (mounted.current) setAIModelStatus(status);
      }
    } catch (reason) {
      if (mounted.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  }, []);

  return {
    recordings,
    selectedId,
    selectedRecording,
    activeJob,
    activeAIJob,
    aiModelStatus,
    error,
    isLoading,
    setSelectedId,
    addRecording,
    rename,
    remove,
    transcribe,
    runAI,
    clearError: () => setError(null),
  };
}
