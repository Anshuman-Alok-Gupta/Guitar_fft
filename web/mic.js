// Browser microphone: captures raw audio (no echo cancellation, noise suppression or AGC,
// which cut sustained notes) and passes 16-bit PCM chunks to onChunk.
export class BrowserMic {
  constructor(onChunk) {
    this.onChunk = onChunk;
    this.stream = null;
    this.ctx = null;
    this.deviceId = "";
    this.label = "";
  }

  get running() { return !!this.ctx; }
  get fs() { return this.ctx?.sampleRate; }

  static get supported() { return !!navigator.mediaDevices?.getUserMedia && "AudioWorkletNode" in window; }

  static async devices() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  }

  async start(deviceId = "") {
    if (!BrowserMic.supported) {
      throw new Error("this page needs HTTPS (or localhost) and a modern browser for microphone access");
    }
    this.stop();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1,
      },
    });
    const ctx = new AudioContext();                     // the device's native sample rate
    try {
      await ctx.audioWorklet.addModule("mic-worklet.js");
      const node = new AudioWorkletNode(ctx, "pcm-sender");
      node.port.onmessage = (e) => this.onChunk(e.data);
      // route through a muted gain to the output so every browser keeps pulling audio
      const mute = ctx.createGain();
      mute.gain.value = 0;
      ctx.createMediaStreamSource(stream).connect(node).connect(mute).connect(ctx.destination);
      await ctx.resume();
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      throw err;
    }
    this.stream = stream;
    this.ctx = ctx;
    this.deviceId = deviceId;
    this.label = stream.getAudioTracks()[0]?.label || "Browser microphone";
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.stream = null;
    this.ctx = null;
  }
}
