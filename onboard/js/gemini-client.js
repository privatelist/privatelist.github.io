/**
 * Gemini Live API WebSocket Client
 * Handles real-time audio/video streaming to Gemini
 */

export class GeminiClient {
    constructor(options) {
        this.apiKey = options.apiKey;
        this.model = options.model || 'gemini-2.5-flash-native-audio-preview-12-2025';
        this.systemPrompt = options.systemPrompt || '';
        this.onAudio = options.onAudio || (() => {});
        this.onTranscript = options.onTranscript || (() => {});
        this.onToolCall = options.onToolCall || (() => {});
        this.onError = options.onError || (() => {});
        
        this.ws = null;
        this.isConnected = false;
        this.isReady = false;
    }

    async connect() {
        return new Promise((resolve, reject) => {
            // Use v1beta API
            const wsUrl = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=${this.apiKey}`;
            
            console.log('Connecting to Gemini...');
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('Gemini WebSocket connected');
                this.isConnected = true;
                this.sendSetup();
            };
            
            this.ws.onmessage = (event) => {
                this.handleMessage(event.data);
                // Resolve on first successful message (setup complete)
                if (!this.isReady) {
                    this.isReady = true;
                    resolve();
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('Gemini WebSocket error:', error);
                this.onError(error);
                reject(error);
            };
            
            this.ws.onclose = (event) => {
                console.log('Gemini WebSocket closed', event.code, event.reason);
                this.isConnected = false;
                this.isReady = false;
                if (!this.isReady) {
                    reject(new Error(`WebSocket closed: ${event.code} ${event.reason}`));
                }
            };

            // Timeout after 15 seconds
            setTimeout(() => {
                if (!this.isReady) {
                    reject(new Error('Connection timeout'));
                }
            }, 15000);
        });
    }

    sendSetup() {
        const setupMessage = {
            setup: {
                model: `models/${this.model}`,
                generationConfig: {
                    responseModalities: ['AUDIO']
                },
                systemInstruction: {
                    parts: [{ text: this.systemPrompt }]
                },
                tools: [{
                    functionDeclarations: [{
                        name: 'execute',
                        description: 'Execute a task using the connected AI system. Use this when you need to take an action on behalf of the client.',
                        parameters: {
                            type: 'OBJECT',
                            properties: {
                                task: {
                                    type: 'STRING',
                                    description: 'Description of the task to execute'
                                }
                            },
                            required: ['task']
                        }
                    }]
                }],
                realtimeInputConfig: {
                    automaticActivityDetection: {
                        disabled: false
                    }
                }
            }
        };
        
        console.log('Sending setup message');
        this.send(setupMessage);
    }

    handleMessage(data) {
        try {
            if (typeof data === 'string') {
                const message = JSON.parse(data);
                console.log('Received message:', Object.keys(message));
                this.processMessage(message);
            } else if (data instanceof Blob) {
                data.arrayBuffer().then(buffer => {
                    this.onAudio(buffer);
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
                    if (part.text) {
                        this.onTranscript(part.text, false);
                    }
                    if (part.inlineData && part.inlineData.mimeType.startsWith('audio/')) {
                        const audioData = this.base64ToArrayBuffer(part.inlineData.data);
                        this.onAudio(audioData);
                    }
                }
            }

            // Handle input transcript
            if (content.inputTranscript) {
                this.onTranscript(content.inputTranscript, true);
            }

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
    }

    sendAudio(audioData) {
        if (!this.isConnected || !this.isReady) return;
        
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
        if (!this.isConnected || !this.isReady) return;
        
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
        this.isReady = false;
    }

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
