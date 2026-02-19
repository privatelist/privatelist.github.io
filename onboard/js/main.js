/**
 * PLC Screen Share Onboarding - Main Entry Point
 */

import { GeminiClient } from './gemini-client.js?v=4';
import { AudioManager } from './audio-manager.js?v=4';
import { ScreenManager } from './screen-manager.js?v=4';
import { OpenClawBridge } from './openclaw-bridge.js?v=4';

class OnboardingApp {
    constructor() {
        this.config = window.ONBOARDING_CONFIG;
        this.gemini = null;
        this.audio = null;
        this.screen = null;
        this.openclaw = null;
        this.isSessionActive = false;
        this.isMuted = false;
        
        this.initElements();
        this.initEventListeners();
    }

    initElements() {
        // Screens
        this.welcomeScreen = document.getElementById('welcomeScreen');
        this.sessionScreen = document.getElementById('sessionScreen');
        this.endScreen = document.getElementById('endScreen');
        
        // Buttons
        this.startBtn = document.getElementById('startBtn');
        this.muteBtn = document.getElementById('muteBtn');
        this.endBtn = document.getElementById('endBtn');
        this.restartBtn = document.getElementById('restartBtn');
        
        // Status
        this.statusDot = document.querySelector('.status-dot');
        this.statusText = document.querySelector('.status-text');
        
        // Session elements
        this.screenPreview = document.getElementById('screenPreview');
        this.previewPlaceholder = document.getElementById('previewPlaceholder');
        this.transcript = document.getElementById('transcript');
        this.micIcon = document.getElementById('micIcon');
        this.speakingIndicator = document.getElementById('speakingIndicator');
    }

    initEventListeners() {
        this.startBtn.addEventListener('click', () => this.startSession());
        this.muteBtn.addEventListener('click', () => this.toggleMute());
        this.endBtn.addEventListener('click', () => this.endSession());
        this.restartBtn.addEventListener('click', () => this.restart());
    }

    showScreen(screenName) {
        this.welcomeScreen.classList.add('hidden');
        this.sessionScreen.classList.add('hidden');
        this.endScreen.classList.add('hidden');
        
        if (screenName === 'welcome') {
            this.welcomeScreen.classList.remove('hidden');
        } else if (screenName === 'session') {
            this.sessionScreen.classList.remove('hidden');
        } else if (screenName === 'end') {
            this.endScreen.classList.remove('hidden');
        }
    }

    updateStatus(status, isActive = false) {
        this.statusText.textContent = status;
        this.statusDot.classList.remove('connected', 'active');
        if (isActive) {
            this.statusDot.classList.add('active');
        } else if (status === 'Connected') {
            this.statusDot.classList.add('connected');
        }
    }

    addMessage(text, type = 'ai') {
        const msg = document.createElement('div');
        msg.className = `message ${type}`;
        msg.textContent = text;
        this.transcript.appendChild(msg);
        this.transcript.scrollTop = this.transcript.scrollHeight;
    }

    async startSession() {
        try {
            this.updateStatus('Starting...', false);
            this.startBtn.disabled = true;
            this.startBtn.textContent = 'Starting...';

            // Initialize screen capture
            this.screen = new ScreenManager();
            const stream = await this.screen.start();
            
            if (stream) {
                this.screenPreview.srcObject = stream;
                this.previewPlaceholder.classList.add('hidden');
            }

            // Initialize audio
            this.audio = new AudioManager();
            await this.audio.start();

            // Initialize OpenClaw bridge
            this.openclaw = new OpenClawBridge(
                this.config.openClawHost,
                this.config.openClawPort,
                this.config.openClawToken
            );

            // Initialize Gemini
            this.gemini = new GeminiClient({
                apiKey: this.config.geminiApiKey,
                model: this.config.geminiModel,
                systemPrompt: this.config.systemPrompt,
                onAudio: (audioData) => this.audio.play(audioData),
                onTranscript: (text, isUser) => this.addMessage(text, isUser ? 'user' : 'ai'),
                onToolCall: (tool) => this.handleToolCall(tool),
                onError: (error) => this.handleError(error)
            });

            await this.gemini.connect();

            // Set up audio streaming to Gemini
            this.audio.onAudioData = (data) => {
                if (!this.isMuted && this.gemini) {
                    this.gemini.sendAudio(data);
                }
            };

            // Set up screen frame streaming to Gemini
            this.screen.onFrame = (frameData) => {
                if (this.gemini) {
                    this.gemini.sendImage(frameData);
                }
            };

            this.isSessionActive = true;
            this.showScreen('session');
            this.updateStatus('Connected', true);
            this.addMessage('Session started. AI assistant is connecting...', 'system');

        } catch (error) {
            console.error('Failed to start session:', error);
            this.handleError(error);
            this.startBtn.disabled = false;
            this.startBtn.textContent = 'Start Session';
        }
    }

    async handleToolCall(toolCall) {
        if (toolCall.name === 'execute' && this.openclaw) {
            try {
                this.addMessage(`Executing: ${toolCall.args.task}`, 'system');
                const result = await this.openclaw.execute(toolCall.args.task);
                this.gemini.sendToolResponse(toolCall.id, result);
            } catch (error) {
                this.gemini.sendToolResponse(toolCall.id, { error: error.message });
            }
        }
    }

    handleError(error) {
        console.error('Error:', error);
        this.addMessage(`Error: ${error.message || error}`, 'system');
        this.updateStatus('Error', false);
    }

    toggleMute() {
        this.isMuted = !this.isMuted;
        this.muteBtn.textContent = this.isMuted ? 'Unmute' : 'Mute';
        this.micIcon.classList.toggle('muted', this.isMuted);
    }

    async endSession() {
        this.isSessionActive = false;
        this.updateStatus('Ending...', false);

        if (this.gemini) {
            this.gemini.disconnect();
            this.gemini = null;
        }

        if (this.audio) {
            this.audio.stop();
            this.audio = null;
        }

        if (this.screen) {
            this.screen.stop();
            this.screen = null;
        }

        this.screenPreview.srcObject = null;
        this.updateStatus('Ended', false);
        this.showScreen('end');
    }

    restart() {
        this.transcript.innerHTML = '';
        this.previewPlaceholder.classList.remove('hidden');
        this.startBtn.disabled = false;
        this.startBtn.textContent = 'Start Session';
        this.isMuted = false;
        this.muteBtn.textContent = 'Mute';
        this.micIcon.classList.remove('muted');
        this.updateStatus('Ready', false);
        this.showScreen('welcome');
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new OnboardingApp();
});
