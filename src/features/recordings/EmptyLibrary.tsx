import { Mic } from "lucide-react";

interface EmptyLibraryProps {
  isLoading: boolean;
  onNewRecording: () => void;
}

export function EmptyLibrary({ isLoading, onNewRecording }: EmptyLibraryProps) {
  return (
    <div className="empty-library">
      <h1>No recordings</h1>
      <button className="empty-start-button" disabled={isLoading} onClick={onNewRecording} type="button">
        <Mic size={16} /><span>Start a new recording</span>
      </button>
    </div>
  );
}
