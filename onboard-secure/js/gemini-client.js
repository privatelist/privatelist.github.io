/**
 * Gemini Live API WebSocket Client
 * Handles real-time audio/video streaming to Gemini
 */

export class GeminiClient {
    constructor(options) {
        this.apiKey = options.apiKey;
        this.model = options.model || 'gemini-2.0-flash-exp';
        this.systemPrompt = options.systemPrompt || '';
        this.onAudio = options.onAudio || (() => {});
        this.onTranscript = options.onTranscript || (() => {});
        this.onToolCall = options.onToolCall || (() => {});
        this.onError = options.onError || (() => {});
        
        this.ws = null;
        this.isConnected = false;
        this.sessionId = null;
    }

    async connect() {
        return new Promise((resolve, reject) => {
            // Use v1beta API with ephemeral token (BidiGenerateContentConstrained endpoint)
            const isEphemeralToken = this.apiKey.startsWith('auth_tokens/');
            const endpoint = isEphemeralToken ? 'BidiGenerateContentConstrained' : 'BidiGenerateContent';
            const paramName = isEphemeralToken ? 'access_token' : 'key';
            const wsUrl = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.${endpoint}?${paramName}=${this.apiKey}`;
            
            console.log('Connecting to Gemini...', isEphemeralToken ? '(ephemeral token)' : '(API key)');
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('Gemini WebSocket connected');
                this.sendSetup();
                this.isConnected = true;
                resolve();
            };
            
            this.ws.onmessage = (event) => {
                this.handleMessage(event.data);
            };
            
            this.ws.onerror = (error) => {
                console.error('Gemini WebSocket error:', error);
                this.onError(error);
                reject(error);
            };
            
            this.ws.onclose = (event) => {
                console.log('Gemini WebSocket closed', event.code, event.reason);
                this.isConnected = false;
            };
        });
    }

    sendSetup() {
        console.log('Sending setup message');
        // Send initial setup message
        const setupMessage = {
            setup: {
                model: `models/${this.model}`,
                generationConfig: {
                    responseModalities: ['AUDIO'],
                    speechConfig: {
                        voiceConfig: {
                            prebuiltVoiceConfig: {
                                voiceName: 'Aoede'
                            }
                        }
                    }
                },
                systemInstruction: {
                    parts: [{ text: this.systemPrompt }]
                }
            }
        };
        
        this.send(setupMessage);
    }

    handleMessage(data) {
        try {
            // Handle both text and binary messages
            if (typeof data === 'string') {
                const message = JSON.parse(data);
                this.processMessage(message);
            } else if (data instanceof Blob) {
                // Blob might be JSON (sent as binary) - try parsing as text first
                data.text().then(text => {
                    try {
                        const message = JSON.parse(text);
                        console.log('Parsed Blob as JSON');
                        this.processMessage(message);
                    } catch (e) {
                        // If not JSON, treat as raw binary audio
                        console.log('Blob is raw binary, not JSON');
                        data.arrayBuffer().then(buffer => {
                            this.onAudio(buffer);
                        });
                    }
                });
            }
        } catch (error) {
            console.error('Error handling Gemini message:', error);
        }
    }

    processMessage(message) {
        // Handle setup complete
        if (message.setupComplete) {
            console.log('Gemini setup complete');
            return;
        }

        // Handle server content (responses)
        if (message.serverContent) {
            const content = message.serverContent;
            
            // Handle model turn (AI speaking)
            if (content.modelTurn) {
                const parts = content.modelTurn.parts || [];
                for (const part of parts) {
                    // Text response
                    if (part.text) {
                        console.log('AI text response:', part.text.substring(0, 100) + (part.text.length > 100 ? '...' : ''));
                        this.onTranscript(part.text, false);
                    }
                    // Audio response
                    if (part.inlineData && part.inlineData.mimeType.startsWith('audio/')) {
                        console.log('Audio received:', part.inlineData.mimeType, 'size:', part.inlineData.data.length);
                        const audioData = this.base64ToArrayBuffer(part.inlineData.data);
                        this.onAudio(audioData, part.inlineData.mimeType);
                    }
                }
            }

            // Handle turn complete
            if (content.turnComplete) {
                console.log('Turn complete');
            }
        }

        // Handle tool calls
        if (message.toolCall) {
            const functionCalls = message.toolCall.functionCalls || [];
            for (const fc of functionCalls) {
                this.onToolCall({
                    id: fc.id,
                    name: fc.name,
                    args: fc.args
                });
            }
        }

        // Handle user transcript (what was heard)
        if (message.serverContent?.inputTranscript) {
            console.log('User transcript:', message.serverContent.inputTranscript);
            this.onTranscript(message.serverContent.inputTranscript, true);
        }
    }

    sendAudio(audioData) {
        if (!this.isConnected) return;
        
        const base64Audio = this.arrayBufferToBase64(audioData);
        
        const message = {
            realtimeInput: {
                mediaChunks: [{
                    mimeType: 'audio/pcm;rate=16000',
                    data: base64Audio
                }]
            }
        };
        
        this.send(message);
    }

    sendImage(imageData) {
        if (!this.isConnected) {
            console.log('Cannot send image - not connected');
            return;
        }
        
        // imageData should be base64 JPEG
        console.log('Sending image frame:', imageData.length, 'chars');
        const message = {
            realtimeInput: {
                mediaChunks: [{
                    mimeType: 'image/jpeg',
                    data: imageData
                }]
            }
        };
        
        this.send(message);
    }

    sendToolResponse(toolCallId, result) {
        if (!this.isConnected) return;
        
        const message = {
            toolResponse: {
                functionResponses: [{
                    id: toolCallId,
                    response: result
                }]
            }
        };
        
        this.send(message);
    }

    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        }
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.isConnected = false;
    }

    // Utility functions
    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }
}
