// Runs on the audio thread: converts the mic input to 16-bit PCM and hands it to the page
// in chunks of CHUNK samples (~21 ms at 48 kHz), which the page sends to the server.
const CHUNK = 1024;

class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(CHUNK);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0][0];                     // first channel only (mono)
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        const v = Math.max(-1, Math.min(1, ch[i]));
        this.buf[this.n++] = v < 0 ? v * 32768 : v * 32767;
        if (this.n === CHUNK) {
          this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
          this.buf = new Int16Array(CHUNK);
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-sender", PcmSender);
