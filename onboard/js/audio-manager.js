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
            
            // Create playback context at 24kHz (Gemini output rate)
            // Note: Browser may resample to device rate automatically
            this.playbackContext = new AudioContext({ sampleRate: 24000 });
            console.log('Playback context sample rate:', this.playbackContext.sampleRate);

            // Set up audio processing
            const source = this.captureContext.createMediaStreamSource(this.mediaStream);
            
            // Use ScriptProcessor for capturing (deprecated but widely supported)
            // Buffer size of 4096 samples = ~256ms at 16kHz
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

    play(audioData, mimeType = 'audio/pcm') {
        // Log for debugging - show first few sample values to diagnose format
        const preview = new Int16Array(audioData.slice(0, Math.min(20, audioData.byteLength)));
        const previewStr = Array.from(preview.slice(0, 5)).join(', ');
        console.log('Queueing audio:', mimeType, 'bytes:', audioData.byteLength, 'first samples:', previewStr);
        
        // Queue the audio for playback
        this.playbackQueue.push({ data: audioData, mimeType });
        
        if (!this.isPlaying) {
            this.processPlaybackQueue();
        }
    }

    async processPlaybackQueue() {
        if (this.playbackQueue.length === 0) {
            this.isPlaying = false;
            return;
        }

        this.isPlaying = true;
        const item = this.playbackQueue.shift();
        const audioData = item.data;
        const mimeType = item.mimeType;

        try {
            // Gemini sends audio/pcm at 24kHz, 16-bit signed little-endian
            // Handle odd byte lengths by truncating (Int16Array needs even bytes)
            let buffer = audioData;
            if (buffer.byteLength % 2 !== 0) {
                buffer = buffer.slice(0, buffer.byteLength - 1);
            }
            
            // Convert PCM to AudioBuffer
            const pcmData = new Int16Array(buffer);
            const floatData = new Float32Array(pcmData.length);
            
            for (let i = 0; i < pcmData.length; i++) {
                floatData[i] = pcmData[i] / 32768.0;
            }

            // Try 24kHz first (Gemini's documented output rate)
            // If audio sounds wrong, might need to try 16000 or 48000
            const sampleRate = 24000;
            const audioBuffer = this.playbackContext.createBuffer(1, floatData.length, sampleRate);
            console.log('Audio buffer: samples=' + floatData.length + ', rate=' + sampleRate + ', duration=' + (floatData.length/sampleRate*1000).toFixed(1) + 'ms');
            audioBuffer.getChannelData(0).set(floatData);

            // Create gain node to boost volume
            const gainNode = this.playbackContext.createGain();
            gainNode.gain.value = 2.0; // Boost volume
            gainNode.connect(this.playbackContext.destination);

            // Play the audio
            const source = this.playbackContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(gainNode);
            
            source.onended = () => {
                this.processPlaybackQueue();
            };
            
            source.start();
            console.log('Playing audio chunk:', pcmData.length, 'samples');
        } catch (error) {
            console.error('Audio playback error:', error);
            this.processPlaybackQueue();
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
