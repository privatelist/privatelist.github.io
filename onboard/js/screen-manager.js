/**
 * Screen Manager
 * Handles screen capture and frame extraction for AI vision
 */

export class ScreenManager {
    constructor() {
        this.mediaStream = null;
        this.videoElement = null;
        this.canvas = null;
        this.ctx = null;
        this.frameInterval = null;
        this.onFrame = null;
        this.frameRate = 1; // 1 fps - sufficient for screen content
        this.loggedFirstFrame = false;
        this.loggedBlankWarning = false;
    }

    async start() {
        try {
            // Request screen capture
            this.mediaStream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    cursor: 'always',
                    displaySurface: 'monitor'
                },
                audio: false
            });

            // Create hidden video element for frame extraction
            this.videoElement = document.createElement('video');
            this.videoElement.srcObject = this.mediaStream;
            this.videoElement.autoplay = true;
            this.videoElement.muted = true;

            // Wait for video to be ready
            await new Promise((resolve) => {
                this.videoElement.onloadedmetadata = resolve;
            });

            // Create canvas for frame capture
            this.canvas = document.createElement('canvas');
            this.ctx = this.canvas.getContext('2d');

            // Start frame capture interval
            this.startFrameCapture();

            // Handle stream end (user stops sharing)
            this.mediaStream.getVideoTracks()[0].onended = () => {
                console.log('Screen share ended by user');
                this.stop();
            };

            console.log('Screen capture started');
            return this.mediaStream;

        } catch (error) {
            console.error('Failed to start screen capture:', error);
            throw error;
        }
    }

    startFrameCapture() {
        const intervalMs = 1000 / this.frameRate;
        
        this.frameInterval = setInterval(() => {
            if (this.videoElement && this.onFrame) {
                const frame = this.captureFrame();
                if (frame) {
                    this.onFrame(frame);
                }
            }
        }, intervalMs);
    }

    captureFrame() {
        if (!this.videoElement || !this.canvas || !this.ctx) {
            return null;
        }

        const video = this.videoElement;
        
        // Debug: log video state
        if (video.videoWidth === 0 || video.videoHeight === 0) {
            console.warn('Video has no dimensions yet:', video.videoWidth, 'x', video.videoHeight);
            return null;
        }
        
        // Scale down for efficiency while maintaining readability
        // Max dimension of 1280px should be enough for screen content
        const maxDimension = 1280;
        let width = video.videoWidth;
        let height = video.videoHeight;

        if (width > maxDimension || height > maxDimension) {
            const scale = maxDimension / Math.max(width, height);
            width = Math.round(width * scale);
            height = Math.round(height * scale);
        }

        this.canvas.width = width;
        this.canvas.height = height;

        // Draw video frame to canvas
        this.ctx.drawImage(video, 0, 0, width, height);

        // Test if canvas has actual pixel data
        const imageData = this.ctx.getImageData(0, 0, Math.min(10, width), Math.min(10, height));
        const pixelSum = imageData.data.reduce((sum, val) => sum + val, 0);
        if (pixelSum === 0 && !this.loggedBlankWarning) {
            console.warn('Canvas pixels are all black! DisplayMedia might be blocked from canvas.');
            this.loggedBlankWarning = true;
        }

        // Convert to JPEG base64 (quality 0.7 for balance of size/quality)
        const dataUrl = this.canvas.toDataURL('image/jpeg', 0.7);
        
        // Extract just the base64 data (remove data:image/jpeg;base64, prefix)
        const base64Data = dataUrl.split(',')[1];
        
        // Debug first frame
        if (!this.loggedFirstFrame) {
            console.log('First frame captured:', width, 'x', height, '=', base64Data.length, 'chars');
            this.loggedFirstFrame = true;
        }
        
        return base64Data;
    }

    stop() {
        if (this.frameInterval) {
            clearInterval(this.frameInterval);
            this.frameInterval = null;
        }

        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }

        if (this.videoElement) {
            this.videoElement.srcObject = null;
            this.videoElement = null;
        }

        this.canvas = null;
        this.ctx = null;

        console.log('Screen capture stopped');
    }

    // Adjust frame rate if needed
    setFrameRate(fps) {
        this.frameRate = fps;
        if (this.frameInterval) {
            clearInterval(this.frameInterval);
            this.startFrameCapture();
        }
    }
}
