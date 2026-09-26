// Modern Dashboard JavaScript for Assistive OCR→TTS

class Dashboard {
    constructor(config, voices) {
        this.config = config;
        this.voices = voices;
        this.statusInterval = null;
        this.historyInterval = null;
        this.isRunning = false;
    }

    init() {
        this.setupEventListeners();
        this.updateRangeValues();
        this.loadConfig();
        this.startPolling();
        this.showAlert('info', 'Dashboard loaded. Click "Start" to begin OCR processing.');
    }

    setupEventListeners() {
        // Control buttons
        document.getElementById('startBtn').addEventListener('click', () => this.startPipeline());
        document.getElementById('stopBtn').addEventListener('click', () => this.stopPipeline());
        document.getElementById('replayBtn').addEventListener('click', () => this.replayAudio());
        document.getElementById('testCameraBtn').addEventListener('click', () => this.testCamera());
        document.getElementById('testOcrBtn').addEventListener('click', () => this.testOCR());

        // Form submissions
        document.getElementById('ocrForm').addEventListener('submit', (e) => this.saveOCRConfig(e));
        document.getElementById('ttsForm').addEventListener('submit', (e) => this.saveTTSConfig(e));
        document.getElementById('cameraForm').addEventListener('submit', (e) => this.saveCameraConfig(e));

        // Range inputs - update display values
        document.getElementById('captureInterval').addEventListener('input', (e) => {
            document.getElementById('captureIntervalValue').textContent = parseFloat(e.target.value).toFixed(1);
        });
        document.getElementById('minConfidence').addEventListener('input', (e) => {
            document.getElementById('minConfidenceValue').textContent = parseFloat(e.target.value).toFixed(2);
        });
        document.getElementById('minTextLen').addEventListener('input', (e) => {
            document.getElementById('minTextLenValue').textContent = e.target.value;
        });
        document.getElementById('ttsSpeed').addEventListener('input', (e) => {
            document.getElementById('ttsSpeedValue').textContent = parseFloat(e.target.value).toFixed(1);
        });
        document.getElementById('ttsVolume').addEventListener('input', (e) => {
            document.getElementById('ttsVolumeValue').textContent = parseFloat(e.target.value).toFixed(1);
        });
    }

    updateRangeValues() {
        // Initialize range value displays
        const captureInterval = document.getElementById('captureInterval').value;
        document.getElementById('captureIntervalValue').textContent = parseFloat(captureInterval).toFixed(1);
        
        const minConfidence = document.getElementById('minConfidence').value;
        document.getElementById('minConfidenceValue').textContent = parseFloat(minConfidence).toFixed(2);
        
        const minTextLen = document.getElementById('minTextLen').value;
        document.getElementById('minTextLenValue').textContent = minTextLen;
        
        const ttsSpeed = document.getElementById('ttsSpeed').value;
        document.getElementById('ttsSpeedValue').textContent = parseFloat(ttsSpeed).toFixed(1);
        
        const ttsVolume = document.getElementById('ttsVolume').value;
        document.getElementById('ttsVolumeValue').textContent = parseFloat(ttsVolume).toFixed(1);
    }

    loadConfig() {
        // Load config values into form
        if (this.config.ocr) {
            document.getElementById('ocrEngine').value = this.config.ocr.engine || 'easyocr';
            document.getElementById('ocrLang').value = this.config.ocr.language || 'en';
            document.getElementById('ocrMode').value = this.config.ocr.mode || 'fallback';
            document.getElementById('captureInterval').value = this.config.ocr.capture_interval || 0.5;
            document.getElementById('minConfidence').value = this.config.ocr.min_confidence || 0.5;
            document.getElementById('minTextLen').value = this.config.ocr.min_text_len || 3;
        }

        if (this.config.tts) {
            document.getElementById('ttsEngine').value = this.config.tts.engine || 'coqui';
            document.getElementById('ttsVoice').value = this.config.tts.voice || 'p335';
            document.getElementById('ttsSpeed').value = this.config.tts.speed || 1.0;
            document.getElementById('ttsVolume').value = this.config.tts.volume || 0.9;
        }

        if (this.config.camera) {
            document.getElementById('cameraSource').value = this.config.camera.source_type || 'opencv';
            document.getElementById('cameraId').value = this.config.camera.camera_id || 0;
            document.getElementById('resolution').value = this.config.camera.resolution || '1080p';
        }

        this.updateRangeValues();
    }

    async startPipeline() {
        try {
            const response = await fetch('/api/start', { method: 'POST' });
            const data = await response.json();
            if (data.status === 'started') {
                this.isRunning = true;
                this.updateStatus(true);
                this.showAlert('success', 'Pipeline started successfully!');
            } else {
                this.showAlert('danger', 'Failed to start pipeline');
            }
        } catch (error) {
            this.showAlert('danger', `Error starting pipeline: ${error.message}`);
        }
    }

    async stopPipeline() {
        try {
            const response = await fetch('/api/stop', { method: 'POST' });
            const data = await response.json();
            if (data.status === 'stopped') {
                this.isRunning = false;
                this.updateStatus(false);
                this.showAlert('info', 'Pipeline stopped');
            } else {
                this.showAlert('danger', 'Failed to stop pipeline');
            }
        } catch (error) {
            this.showAlert('danger', `Error stopping pipeline: ${error.message}`);
        }
    }

    async replayAudio() {
        try {
            const response = await fetch('/api/replay');
            if (response.status === 200) {
                const audioBlob = await response.blob();
                const audioUrl = URL.createObjectURL(audioBlob);
                const audio = new Audio(audioUrl);
                audio.play();
                this.showAlert('success', 'Playing last audio...');
            } else {
                const data = await response.json();
                this.showAlert('warning', data.message || 'No audio available');
            }
        } catch (error) {
            this.showAlert('danger', `Error replaying audio: ${error.message}`);
        }
    }

    async testCamera() {
        const btn = document.getElementById('testCameraBtn');
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading-spinner"></span> Testing...';

        try {
            const response = await fetch('/api/test-camera');
            const data = await response.json();
            
            if (data.status === 'ok') {
                this.showAlert('success', 
                    `Camera ${data.message || 'working'}! Frame shape: ${data.frame_shape ? data.frame_shape.join('x') : 'N/A'}`);
            } else {
                this.showAlert('danger', `Camera test failed: ${data.message || 'Unknown error'}`);
            }
        } catch (error) {
            this.showAlert('danger', `Error testing camera: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async testOCR() {
        const btn = document.getElementById('testOcrBtn');
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading-spinner"></span> Testing...';
        // Everything from the server (including OCR text read by the camera) is escaped.
        const esc = (t) => this.escapeHtml(String(t ?? ''));
        const engineList = (engines) => {
            let html = '';
            for (const [engine, d] of Object.entries(engines || {})) {
                const icon = d.status === 'READY' ? '✅' : (d.status === 'DISABLED' ? '⏸️' : '❌');
                html += `${icon} ${esc(engine)}: ${esc(d.status)}`;
                if (d.status !== 'READY' && d.detail) {
                    html += `<br><small style="color: #666;">${esc(d.detail)}</small>`;
                }
                html += '<br>';
            }
            return html;
        };

        try {
            const response = await fetch('/api/test-ocr');
            const data = await response.json();

            if (data.status === 'ok') {
                let message = '<strong>OCR Engines:</strong><br>' + engineList(data.ocr_engines);
                message += '<br><strong>TTS Engines:</strong><br>' + engineList(data.tts_engines);

                const r = data.ocr_test_on_frame;
                if (r) {
                    if (r.error) {
                        message += `<br><strong>Frame OCR Test:</strong> ❌ ${esc(r.error)}`;
                    } else if (r.text) {
                        message += `<br><strong>Frame OCR Test:</strong> ✅ Detected "${esc(r.text.substring(0, 50))}"`;
                        message += `<br>Engine: ${esc(r.engine)}, Confidence: ${(r.confidence * 100).toFixed(1)}%, Score: ${(r.score * 100).toFixed(1)}%`;
                    } else {
                        message += `<br><strong>Frame OCR Test:</strong> ⚠️ No text accepted (${esc(r.reason)})`;
                        if (r.frame_quality && !r.frame_quality.usable) {
                            message += `<br>Frame quality: ${esc(r.frame_quality.reasons.join(', '))}`;
                        }
                    }
                }

                if (data.config) {
                    message += `<br><br><strong>Current Config:</strong>`;
                    message += `<br>Mode: ${esc(data.config.mode)}, Primary engine: ${esc(data.config.engine)}`;
                    message += `<br>Min Confidence: ${esc(data.config.min_confidence)}`;
                    message += `<br>Min Text Length: ${esc(data.config.min_text_len)}`;
                }

                this.showAlert('info', message, true);
            } else {
                this.showAlert('danger', `OCR test failed: ${data.message || 'Unknown error'}`);
            }
        } catch (error) {
            this.showAlert('danger', `Error testing OCR: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    configError(data, what) {
        const details = (data.errors || []).join('; ');
        this.showAlert('danger', `Failed to save ${what}${details ? ': ' + details : ''}`);
    }

    async saveOCRConfig(e) {
        e.preventDefault();
        const btn = document.getElementById('saveOcr');
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading-spinner"></span> Saving...';

        try {
            const payload = {
                ocr: {
                    engine: document.getElementById('ocrEngine').value,
                    language: document.getElementById('ocrLang').value,
                    capture_interval: parseFloat(document.getElementById('captureInterval').value),
                    min_confidence: parseFloat(document.getElementById('minConfidence').value),
                    min_text_len: parseInt(document.getElementById('minTextLen').value),
                    mode: document.getElementById('ocrMode').value
                }
            };

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (data.status === 'saved') {
                this.config.ocr = payload.ocr;
                this.showAlert('success', 'OCR settings saved successfully! Pipeline will restart.');
            } else {
                this.configError(data, 'OCR settings');
            }
        } catch (error) {
            this.showAlert('danger', `Error saving OCR settings: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async saveTTSConfig(e) {
        e.preventDefault();
        const btn = document.getElementById('saveTts');
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading-spinner"></span> Saving...';

        try {
            const payload = {
                tts: {
                    engine: document.getElementById('ttsEngine').value,
                    voice: document.getElementById('ttsVoice').value,
                    speed: parseFloat(document.getElementById('ttsSpeed').value),
                    volume: parseFloat(document.getElementById('ttsVolume').value)
                }
            };

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (data.status === 'saved') {
                this.config.tts = payload.tts;
                this.showAlert('success', 'TTS settings saved successfully!');
            } else {
                this.configError(data, 'TTS settings');
            }
        } catch (error) {
            this.showAlert('danger', `Error saving TTS settings: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async saveCameraConfig(e) {
        e.preventDefault();
        const btn = document.getElementById('saveCamera');
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="loading-spinner"></span> Saving...';

        try {
            const payload = {
                camera: {
                    source_type: document.getElementById('cameraSource').value,
                    camera_id: parseInt(document.getElementById('cameraId').value),
                    resolution: document.getElementById('resolution').value
                }
            };

            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (data.status === 'saved') {
                this.config.camera = payload.camera;
                this.showAlert('success', 'Camera settings saved successfully! Pipeline will restart.');
            } else {
                this.configError(data, 'camera settings');
            }
        } catch (error) {
            this.showAlert('danger', `Error saving camera settings: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async updateStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            if (data.pipeline) {
                this.isRunning = data.pipeline.running || false;
                this.updateStatusBadge(this.isRunning);
                
                if (data.pipeline.last_text) {
                    const output = document.getElementById('ocrOutput');
                    output.textContent = data.pipeline.last_text;
                    output.classList.add('fade-in');
                    setTimeout(() => output.classList.remove('fade-in'), 300);
                }
            }
        } catch (error) {
            console.error('Error updating status:', error);
        }
    }

    async updateHistory() {
        try {
            const response = await fetch('/api/history');
            const data = await response.json();
            
            const list = document.getElementById('historyList');
            const count = document.getElementById('historyCount');
            
            if (data.history && data.history.length > 0) {
                list.innerHTML = '';
                count.textContent = data.history.length;
                
                data.history.forEach((h, index) => {
                    const item = document.createElement('div');
                    item.className = 'history-item fade-in';
                    item.style.animationDelay = `${index * 0.05}s`;
                    
                    const time = new Date(h.ts * 1000).toLocaleString();
                    const engine = h.engine ? ` [${h.engine}]` : '';
                    const confidence = h.confidence ? ` (${(h.confidence * 100).toFixed(0)}%)` : '';
                    
                    item.innerHTML = `
                        <div class="history-item-time">${time}${engine}${confidence}</div>
                        <div class="history-item-text">${this.escapeHtml(h.text)}</div>
                    `;
                    list.appendChild(item);
                });
            } else {
                list.innerHTML = '<div class="text-muted text-center">No history yet</div>';
                count.textContent = '0';
            }
        } catch (error) {
            console.error('Error updating history:', error);
        }
    }

    updateStatusBadge(isRunning) {
        const badge = document.getElementById('statusBadge');
        if (isRunning) {
            badge.textContent = 'Running';
            badge.className = 'status-badge status-running';
        } else {
            badge.textContent = 'Stopped';
            badge.className = 'status-badge status-stopped';
        }
    }

    showAlert(type, message, isHtml = false) {
        const container = document.getElementById('alertContainer');
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} fade-in`;
        alert.setAttribute('role', 'alert');
        
        if (isHtml) {
            alert.innerHTML = message;
        } else {
            alert.textContent = message;
        }
        
        container.innerHTML = '';
        container.appendChild(alert);
        
        // Auto-remove after 5 seconds for success/info, 10 for errors
        const timeout = (type === 'danger' || type === 'warning') ? 10000 : 5000;
        setTimeout(() => {
            alert.classList.remove('fade-in');
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, timeout);
    }

    startPolling() {
        // Update status every second
        this.statusInterval = setInterval(() => this.updateStatus(), 1000);
        
        // Update history every 3 seconds
        this.historyInterval = setInterval(() => this.updateHistory(), 3000);
        
        // Initial updates
        this.updateStatus();
        this.updateHistory();
    }

    stopPolling() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
        }
        if (this.historyInterval) {
            clearInterval(this.historyInterval);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export for use in HTML
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Dashboard;
}

