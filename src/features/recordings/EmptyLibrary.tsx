import { ArrowUpRight, AudioLines, Mic } from "lucide-react";

interface EmptyLibraryProps {
  isLoading: boolean;
  onNewRecording: () => void;
}

export function EmptyLibrary({ isLoading, onNewRecording }: EmptyLibraryProps) {
  return (
    <div className="empty-library">
      <div className="empty-orbit">
        <div className="empty-orbit-inner"><AudioLines size={27} strokeWidth={1.4} /></div>
        <span className="orbit-dot orbit-dot-one" /><span className="orbit-dot orbit-dot-two" />
      </div>
      <div className="eyebrow"><span className="eyebrow-line" />A QUIETER WAY TO CAPTURE</div>
      <h1>Make room for<br /><em>every thought.</em></h1>
      <p className="empty-copy">Record a moment. Find the words later.<br />Your voice stays yours, always.</p>
      <button className="empty-start-button" disabled={isLoading} onClick={onNewRecording} type="button">
        <Mic size={16} /><span>Start a new recording</span><ArrowUpRight size={15} />
      </button>
      <div className="empty-footnote"><span />Transcribed privately on your device</div>
    </div>
  );
}
