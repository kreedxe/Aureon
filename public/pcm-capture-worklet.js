class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(1024);
    this.offset = 0;
  }

  process(inputs, outputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      let sourceOffset = 0;
      while (sourceOffset < channel.length) {
        const count = Math.min(channel.length - sourceOffset, this.buffer.length - this.offset);
        this.buffer.set(channel.subarray(sourceOffset, sourceOffset + count), this.offset);
        this.offset += count;
        sourceOffset += count;
        if (this.offset === this.buffer.length) {
          const block = this.buffer;
          this.buffer = new Float32Array(1024);
          this.offset = 0;
          this.port.postMessage(block, [block.buffer]);
        }
      }
    }

    const output = outputs[0]?.[0];
    if (output) output.fill(0);
    return true;
  }
}

registerProcessor("aureon-pcm-capture", PcmCaptureProcessor);
