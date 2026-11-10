import { useEffect, useRef } from "react";

interface WaveformProps {
  analyser?: AnalyserNode | null;
  progress?: number;
  variant?: "live" | "playback";
  className?: string;
}

export function Waveform({ analyser, progress = 0, variant = "live", className = "" }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    let frame = 0;
    let animation = 0;
    const samples = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;

    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const width = Math.max(1, bounds.width);
      const height = Math.max(1, bounds.height);
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const count = Math.max(28, Math.floor(width / 5));
      const gap = 2;
      const barWidth = Math.max(1.5, (width - count * gap) / count);
      const styles = getComputedStyle(canvas);
      const activeColor = styles.getPropertyValue("--waveform-active").trim();
      const playedColor = styles.getPropertyValue("--waveform-played").trim();
      const idleColor = styles.getPropertyValue("--waveform-idle").trim();
      if (samples && analyser) analyser.getByteFrequencyData(samples);
      for (let index = 0; index < count; index += 1) {
        const source = samples ? samples[Math.floor(index / count * samples.length)] / 255 : 0;
        const wave = 0.18 + Math.abs(Math.sin(index * 0.23 + frame * 0.035) * Math.cos(index * 0.071)) * 0.62;
        const amplitude = samples ? Math.max(0.09, source * 1.35) : wave;
        const barHeight = Math.max(3, height * amplitude);
        const x = index * (barWidth + gap);
        const y = (height - barHeight) / 2;
        const isPlayed = variant === "playback" && index / count <= progress;
        context.fillStyle = variant === "live" ? activeColor : isPlayed ? playedColor : idleColor;
        context.globalAlpha = variant === "live" ? 0.38 + amplitude * 0.62 : 1;
        context.beginPath();
        context.rect(x, y, barWidth, barHeight);
        context.fill();
      }
      context.globalAlpha = 1;
      frame += 1;
      if (variant === "live" && analyser) animation = requestAnimationFrame(draw);
    };

    draw();
    if (variant === "live" && analyser) animation = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animation);
  }, [analyser, progress, variant]);

  return <canvas aria-hidden="true" className={`waveform-canvas ${className}`} ref={canvasRef} />;
}
