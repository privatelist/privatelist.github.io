/**
 * Audio Manager
 * Handles microphone capture (16kHz) and audio playback (24kHz)
 */

export class AudioManager {
    constructor() {
        this.captureContext = null;
        this.playbackContext = null;
        this.mediaStream = null;
        this.processor = null;
        this.onAudioData = null;
        this.playbackQueue = [];
        this.isPlaying = false;
        this.nextPlayTime = 0;
    }

    async start() {
        try {
            // Get microphone access
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            // Create capture context at 16kHz
            this.captureContext = new AudioContext({ sampleRate: 16000 });
            
            // Create playback context at 24kHz for Gemini output
            this.playbackContext = new AudioContext({ sampleRate: 24000 });
            this.nextPlayTime = this.playbackContext.currentTime;

            // Set up audio processing
            const source = this.captureContext.createMediaStreamSource(this.mediaStream);
            
            // Use ScriptProcessor for capturing
            this.processor = this.captureContext.createScriptProcessor(4096, 1, 1);
            
            this.processor.onaudioprocess = (event) => {
                if (this.onAudioData) {
                    const inputData = event.inputBuffer.getChannelData(0);
                    const pcmData = this.floatTo16BitPCM(inputData);
                    this.onAudioData(pcmData.buffer);
                }
            };

            source.connect(this.processor);
            this.processor.connect(this.captureContext.destination);

            console.log('Audio capture started');
        } catch (error) {
            console.error('Failed to start audio:', error);
            throw error;
        }
    }

    play(audioData) {
        if (!audioData || audioData.byteLength === 0) {
            return;
        }

        try {
            // Ensure byte length is even for Int16Array
            let buffer = audioData;
            if (buffer instanceof ArrayBuffer) {
                // Already ArrayBuffer
            } else if (buffer.buffer instanceof ArrayBuffer) {
                buffer = buffer.buffer;
            }
            
            let byteLength = buffer.byteLength;
            if (byteLength % 2 !== 0) {
                buffer = buffer.slice(0, byteLength - 1);
                byteLength = buffer.byteLength;
            }

            if (byteLength < 2) {
                return;
            }

            // Convert PCM Int16 to Float32
            const pcmData = new Int16Array(buffer);
            const floatData = new Float32Array(pcmData.length);
            
            for (let i = 0; i < pcmData.length; i++) {
                floatData[i] = pcmData[i] / 32768.0;
            }

            // Create AudioBuffer at 24kHz
            const audioBuffer = this.playbackContext.createBuffer(1, floatData.length, 24000);
            audioBuffer.getChannelData(0).set(floatData);

            // Schedule playback
            const source = this.playbackContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this.playbackContext.destination);
            
            // Schedule at next available time to avoid gaps/overlaps
            const now = this.playbackContext.currentTime;
            const startTime = Math.max(now, this.nextPlayTime);
            source.start(startTime);
            
            // Update next play time
            this.nextPlayTime = startTime + audioBuffer.duration;

        } catch (error) {
            console.error('Audio playback error:', error);
        }
    }

    stop() {
        if (this.processor) {
            this.processor.disconnect();
            this.processor = null;
        }

        if (this.captureContext) {
            this.captureContext.close();
            this.captureContext = null;
        }

        if (this.playbackContext) {
            this.playbackContext.close();
            this.playbackContext = null;
        }

        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }

        this.playbackQueue = [];
        this.isPlaying = false;

        console.log('Audio stopped');
    }

    // Convert Float32Array to Int16Array (PCM)
    floatTo16BitPCM(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return int16Array;
    }
}
