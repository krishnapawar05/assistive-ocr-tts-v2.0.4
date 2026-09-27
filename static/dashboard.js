// Smart Vision Assist v2.0.4 — Accessible Dashboard JavaScript
// Audio-First, Accessible, Screen-Reader and Keyboard Enabled

class Dashboard {
    constructor(config, voices) {
        this.config = config;
        this.voices = voices;
        this.statusInterval = null;
        this.historyInterval = null;
        this.isRunning = false;
        this.lastAnnouncement = '';
        this.lastTextSeen = '';
        this.lastMovingState = null;
        this.lastCameraState = null;
        this.lastSpeakingState = null;
    }

    init() {
        this.setupEventListeners();
        this.setupKeyboardShortcuts();
        this.updateRangeValues();
        this.loadConfig();
        this.startPolling();
        this.announce('Smart Vision Assist ready. Press Space bar or click Start System to begin reading.');
        this.showAlert('info', 'System ready. Press Space to start reading, R to replay text, Esc to stop speech.');
    }

    setupEventListeners() {
        // Primary Control buttons
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        const replayBtn = document.getElementById('replayBtn');
        const stopSpeechBtn = document.getElementById('stopSpeechBtn');
        const testCameraBtn = document.getElementById('testCameraBtn');
        const testOcrBtn = document.getElementById('testOcrBtn');

        if (startBtn) startBtn.addEventListener('click', () => this.startPipeline());
        if (stopBtn) stopBtn.addEventListener('click', () => this.stopPipeline());
        if (replayBtn) replayBtn.addEventListener('click', () => this.replayAudio());
        if (stopSpeechBtn) stopSpeechBtn.addEventListener('click', () => this.stopSpeech());
        if (testCameraBtn) testCameraBtn.addEventListener('click', () => this.testCamera());
        if (testOcrBtn) testOcrBtn.addEventListener('click', () => this.testOCR());

        // Form submissions (Diagnostics & Settings)
        const ocrForm = document.getElementById('ocrForm');
        const ttsForm = document.getElementById('ttsForm');
        const cameraForm = document.getElementById('cameraForm');

        if (ocrForm) ocrForm.addEventListener('submit', (e) => this.saveOCRConfig(e));
        if (ttsForm) ttsForm.addEventListener('submit', (e) => this.saveTTSConfig(e));
        if (cameraForm) cameraForm.addEventListener('submit', (e) => this.saveCameraConfig(e));

        // Range inputs - update display values
        const rangeMap = [
            ['captureInterval', 'captureIntervalValue', 1],
            ['minConfidence', 'minConfidenceValue', 2],
            ['minTextLen', 'minTextLenValue', 0],
            ['ttsSpeed', 'ttsSpeedValue', 1],
            ['ttsVolume', 'ttsVolumeValue', 1]
        ];

        rangeMap.forEach(([inputId, valId, decimals]) => {
            const input = document.getElementById(inputId);
            const valSpan = document.getElementById(valId);
            if (input && valSpan) {
                input.addEventListener('input', (e) => {
                    const num = parseFloat(e.target.value);
                    valSpan.textContent = decimals > 0 ? num.toFixed(decimals) : String(parseInt(num, 10));
                });
            }
        });
    }

    setupKeyboardShortcuts() {
        window.addEventListener('keydown', (e) => {
            // Never hijack typing inside text inputs, dropdowns, or textareas
            if (e.target && (e.target.matches('input, select, textarea') || e.target.isContentEditable)) {
                return;
            }

            if (e.code === 'Space') {
                e.preventDefault();
                if (this.isRunning) {
                    this.stopPipeline();
                } else {
                    this.startPipeline();
                }
            } else if (e.key === 'r' || e.key === 'R') {
                e.preventDefault();
                this.replayAudio();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.stopSpeech();
            }
        });
    }

    announce(text) {
        const sr = document.getElementById('srLiveAnnouncements');
        if (!sr || !text || text === this.lastAnnouncement) return;
        this.lastAnnouncement = text;
        sr.textContent = '';
        setTimeout(() => {
            sr.textContent = text;
        }, 50);
    }

    updateRangeValues() {
        const captureInterval = document.getElementById('captureInterval');
        const minConfidence = document.getElementById('minConfidence');
        const minTextLen = document.getElementById('minTextLen');
        const ttsSpeed = document.getElementById('ttsSpeed');
        const ttsVolume = document.getElementById('ttsVolume');

        if (captureInterval) {
            const span = document.getElementById('captureIntervalValue');
            if (span) span.textContent = parseFloat(captureInterval.value).toFixed(1);
        }
        if (minConfidence) {
            const span = document.getElementById('minConfidenceValue');
            if (span) span.textContent = parseFloat(minConfidence.value).toFixed(2);
        }
        if (minTextLen) {
            const span = document.getElementById('minTextLenValue');
            if (span) span.textContent = minTextLen.value;
        }
        if (ttsSpeed) {
            const span = document.getElementById('ttsSpeedValue');
            if (span) span.textContent = parseFloat(ttsSpeed.value).toFixed(1);
        }
        if (ttsVolume) {
            const span = document.getElementById('ttsVolumeValue');
            if (span) span.textContent = parseFloat(ttsVolume.value).toFixed(1);
        }
    }

    loadConfig() {
        if (this.config.ocr) {
            const ocr = this.config.ocr;
            const elEngine = document.getElementById('ocrEngine');
            const elLang = document.getElementById('ocrLang');
            const elMode = document.getElementById('ocrMode');
            const elCap = document.getElementById('captureInterval');
            const elConf = document.getElementById('minConfidence');
            const elLen = document.getElementById('minTextLen');

            if (elEngine) elEngine.value = ocr.engine || 'easyocr';
            if (elLang) elLang.value = ocr.language || 'en';
            if (elMode) elMode.value = ocr.mode || 'fallback';
            if (elCap) elCap.value = ocr.capture_interval || 0.5;
            if (elConf) elConf.value = ocr.min_confidence || 0.5;
            if (elLen) elLen.value = ocr.min_text_len || 3;
        }

        if (this.config.tts) {
            const tts = this.config.tts;
            const elEngine = document.getElementById('ttsEngine');
            const elVoice = document.getElementById('ttsVoice');
            const elSpeed = document.getElementById('ttsSpeed');
            const elVol = document.getElementById('ttsVolume');

            if (elEngine) elEngine.value = tts.engine || 'coqui';
            if (elVoice) elVoice.value = tts.voice || 'p335';
            if (elSpeed) elSpeed.value = tts.speed || 1.0;
            if (elVol) elVol.value = tts.volume || 0.9;
        }

        if (this.config.camera) {
            const cam = this.config.camera;
            const elSource = document.getElementById('cameraSource');
            const elId = document.getElementById('cameraId');
            const elRes = document.getElementById('resolution');

            if (elSource) elSource.value = cam.source_type || 'opencv';
            if (elId) elId.value = cam.camera_id || 0;
            if (elRes) elRes.value = cam.resolution || '720p';
        }

        this.updateRangeValues();
    }

    async startPipeline() {
        try {
            const response = await fetch('/api/start', { method: 'POST' });
            const data = await response.json();
            if (data.status === 'started') {
                this.isRunning = true;
                this.updateStatusBadge(true);
                this.announce('System started. Camera active. Point camera at document.');
                this.showAlert('success', 'System started. Point camera at text.');
            } else {
                this.showAlert('danger', 'Failed to start camera system.');
            }
        } catch (error) {
            this.showAlert('danger', `Error starting system: ${error.message}`);
        }
    }

    async stopPipeline() {
        try {
            const response = await fetch('/api/stop', { method: 'POST' });
            const data = await response.json();
            if (data.status === 'stopped') {
                this.isRunning = false;
                this.updateStatusBadge(false);
                this.announce('System paused.');
                this.showAlert('info', 'System paused.');
            } else {
                this.showAlert('danger', 'Failed to pause system.');
            }
        } catch (error) {
            this.showAlert('danger', `Error pausing system: ${error.message}`);
        }
    }

    async stopSpeech() {
        try {
            const response = await fetch('/api/stop-speech', { method: 'POST' });
            if (response.ok) {
                this.announce('Speech stopped.');
                const speechBadge = document.getElementById('speechBadge');
                if (speechBadge) {
                    speechBadge.textContent = 'Speech: Stopped';
                    speechBadge.className = 'badge status-pill bg-secondary';
                }
                this.showAlert('info', 'Speech stopped and queue cleared.');
            }
        } catch (error) {
            this.showAlert('warning', `Could not stop speech: ${error.message}`);
        }
    }

    async replayAudio() {
        try {
            // First attempt to fetch synthesized WAV audio
            const response = await fetch('/api/replay');
            if (response.status === 200) {
                const audioBlob = await response.blob();
                const audioUrl = URL.createObjectURL(audioBlob);
                const audio = new Audio(audioUrl);
                audio.play();
                this.announce('Replaying latest audio.');
                this.showAlert('success', 'Replaying last recognized audio...');
                return;
            }

            // Fallback: Re-speak latest recognized text through server TTS
            const fallbackResponse = await fetch('/api/replay-latest', { method: 'POST' });
            const data = await fallbackResponse.json();
            if (fallbackResponse.ok && data.status === 'replaying') {
                this.announce(`Replaying: ${data.text.substring(0, 60)}`);
                this.showAlert('success', `Replaying text: "${data.text.substring(0, 50)}..."`);
            } else {
                this.announce('No recognized text available to replay.');
                this.showAlert('warning', data.message || 'No text recognized yet to replay.');
            }
        } catch (error) {
            this.showAlert('danger', `Error replaying audio: ${error.message}`);
        }
    }

    async testCamera() {
        const btn = document.getElementById('testCameraBtn');
        if (!btn) return;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Testing...';

        try {
            const response = await fetch('/api/test-camera');
            const data = await response.json();
            
            if (data.status === 'ok') {
                const res = data.frame_shape ? `${data.frame_shape[1]}x${data.frame_shape[0]}` : 'N/A';
                this.announce(`Camera hardware working. Resolution ${res}.`);
                this.showAlert('success', `Camera working! Resolution: ${res}`);
            } else {
                const cleanMsg = data.message ? this.humanizeError(data.message) : 'Camera unavailable';
                this.announce(`Camera test failed: ${cleanMsg}`);
                this.showAlert('danger', `Camera test: ${cleanMsg}`);
            }
        } catch (error) {
            this.showAlert('danger', `Camera error: ${error.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async testOCR() {
        const btn = document.getElementById('testOcrBtn');
        if (!btn) return;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Running diagnostics...';
        try {
            const response = await fetch('/api/test-ocr');
            const data = await response.json();
            if (data.status === 'ok') {
                this.showAlert('info', Dashboard.formatOcrTest(data), true);
                if (data.ocr_test_on_frame && data.ocr_test_on_frame.text) {
                    this.announce(`OCR test recognized: ${data.ocr_test_on_frame.text}`);
                }
            } else {
                this.showAlert('danger', `OCR diagnostic error: ${this.escapeHtml(data.message || data.detail || 'Unknown error')}`);
            }
        } catch (error) {
            this.showAlert('danger', `Error running OCR diagnostic: ${this.escapeHtml(error.message)}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    humanizeError(rawError) {
        if (!rawError) return 'System unavailable';
        const lower = String(rawError).toLowerCase();
        if (lower.includes('cannot open camera') || lower.includes('cap_dshow') || lower.includes('no frame')) {
            return 'Camera unavailable. Please check that your webcam is plugged in and not in use by another app.';
        }
        if (lower.includes('timeout')) {
            return 'Processing timed out. Try holding the document steady.';
        }
        return rawError;
    }

    /** HTML for a /api/test-ocr response. Pure (no DOM) so it is unit-tested under Node.
     *  Everything from the server, including OCR text read by the camera, is escaped. */
    static formatOcrTest(data) {
        const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
            (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
        const pct = (x) => `${(Number(x) * 100).toFixed(1)}%`;
        const cfg = data.config || {};
        const ocrEngines = data.ocr_engines || {};
        const engineList = (engines) => {
            let html = '';
            for (const [engine, d] of Object.entries(engines || {})) {
                let icon = '❌';
                let label = d.status;
                if (d.status === 'READY') icon = '✅';
                else if (d.status === 'DISABLED') icon = '⏸️';
                else if (d.status === 'UNINITIALIZED') { icon = '⏳'; label = 'not loaded yet (loads on first use)'; }
                html += `${icon} ${esc(engine)}: ${esc(label)}`;
                if (!['READY', 'UNINITIALIZED'].includes(d.status) && d.detail) {
                    html += `<br><small style="color: #666;">${esc(d.detail)}</small>`;
                }
                html += '<br>';
            }
            return html;
        };
        const REASONS = {
            no_text: 'OCR ran but found no text in the frame',
            below_min_confidence: 'text was found, but its confidence was below Min Confidence',
            below_threshold: 'text was found, but it was rejected by quality scoring',
            no_engine_available: 'no OCR engine is available',
            all_engines_failed: 'every OCR engine that ran failed',
        };

        let message = '<strong>OCR Engines:</strong><br>' + engineList(ocrEngines);
        message += '<br><strong>TTS Engines:</strong><br>' + engineList(data.tts_engines);

        const r = data.ocr_test_on_frame;
        if (r) {
            message += '<br><strong>Frame OCR Test:</strong> ';
            if (r.error) {
                message += `❌ No usable camera frame: ${esc(r.error)}`;
            } else {
                if (r.text) {
                    message += `✅ Detected "${esc(r.text.substring(0, 50))}"`;
                    message += `<br>Engine used: ${esc(r.engine)}, Confidence: ${pct(r.confidence)}, Score: ${pct(r.score)}`;
                } else {
                    message += `⚠️ No text accepted: ${esc(REASONS[r.reason] || r.reason)}`;
                    for (const [engine, conf] of Object.entries(r.low_confidence || {})) {
                        message += `<br>${esc(engine)} confidence ${pct(conf)} &lt; Min Confidence ${pct(cfg.min_confidence)}`;
                    }
                    for (const c of r.candidates || []) {
                        message += `<br>${esc(c.engine)} read "${esc(c.text.substring(0, 50))}" with score ${pct(c.score)}`
                                 + (cfg.min_final_score !== undefined ? ` (needs ${pct(cfg.min_final_score)})` : '');
                    }
                    for (const [engine, code] of Object.entries(r.errors || {})) {
                        message += `<br>${esc(engine)} error: ${esc(code)}`;
                    }
                }
                const SKIPPED = {
                    no_text_region: 'no text region was found by EasyOCR/PaddleOCR, so it was not run',
                    no_region_source: 'it needs EasyOCR or PaddleOCR to find text regions first',
                };
                for (const [engine, why] of Object.entries(r.skipped || {})) {
                    message += `<br>${esc(engine)} skipped: ${esc(SKIPPED[why] || why)}`;
                }
                const primary = cfg.engine;
                const primaryStatus = (ocrEngines[primary] || {}).status;
                if (primary && !(r.engines_run || []).includes(primary)) {
                    message += `<br>ℹ️ Primary engine ${esc(primary)} was skipped (${esc(primaryStatus || 'unknown')})`;
                    message += `; engines tried: ${esc((r.engines_run || []).join(', ') || 'none')}`;
                } else if (r.engines_run && r.engines_run.length) {
                    message += `<br>Engines tried: ${esc(r.engines_run.join(', '))}`;
                }
                if (r.frame) {
                    message += `<br>Frame: ${esc(r.frame.shape.join('×'))}, mean brightness ${esc(r.frame.mean)}`;
                }
                if (r.latency_s !== undefined) message += `, OCR time ${esc(r.latency_s)}s`;
                if (r.frame_quality && !r.frame_quality.usable) {
                    message += `<br>Frame quality: ${esc(r.frame_quality.reasons.join(', '))} (the live pipeline would skip this frame)`;
                }
            }
        }

        message += '<br><br><strong>Current Config:</strong>';
        message += `<br>Mode: ${esc(cfg.mode)}, Primary engine: ${esc(cfg.engine)}`;
        message += `<br>Min Confidence: ${esc(cfg.min_confidence)}`;
        message += `<br>Min Text Length: ${esc(cfg.min_text_len)}`;
        return message;
    }

    configError(data, what) {
        const details = (data.errors || []).join('; ');
        this.showAlert('danger', `Failed to save ${what}${details ? ': ' + details : ''}`);
    }

    async saveOCRConfig(e) {
        e.preventDefault();
        const btn = document.getElementById('saveOcr');
        if (!btn) return;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';

        try {
            const payload = {
                ocr: {
                    engine: document.getElementById('ocrEngine').value,
                    language: document.getElementById('ocrLang').value,
                    capture_interval: parseFloat(document.getElementById('captureInterval').value),
                    min_confidence: parseFloat(document.getElementById('minConfidence').value),
                    min_text_len: parseInt(document.getElementById('minTextLen').value, 10),
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
                this.showAlert('success', 'OCR settings saved successfully! Pipeline reloaded.');
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
        if (!btn) return;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';

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
        if (!btn) return;
        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';

        try {
            const payload = {
                camera: {
                    source_type: document.getElementById('cameraSource').value,
                    camera_id: parseInt(document.getElementById('cameraId').value, 10),
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
                this.showAlert('success', 'Camera settings saved! Reconnecting camera...');
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

    async refreshCameraPreview() {
        const previewImg = document.getElementById('cameraPreview');
        if (!previewImg) return;
        const newImg = new Image();
        newImg.onload = () => {
            previewImg.src = newImg.src;
            previewImg.style.opacity = '1.0';
        };
        newImg.onerror = () => {
            previewImg.style.opacity = '0.5';
        };
        newImg.src = `/api/camera/snapshot?t=${Date.now()}`;
    }

    async updateStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();
            
            if (data.pipeline) {
                const pipe = data.pipeline;
                this.isRunning = pipe.running || false;
                this.updateStatusBadge(this.isRunning);
                
                // Refresh viewfinder thumbnail while stream is active
                if (this.isRunning) {
                    this.refreshCameraPreview();
                }

                // Camera status & motion
                const motionBadge = document.getElementById('motionBadge');
                const isMoving = pipe.motion ? pipe.motion.is_moving : false;
                const camState = pipe.camera ? pipe.camera.state : 'stopped';

                if (motionBadge) {
                    if (!this.isRunning) {
                        motionBadge.textContent = 'Camera: Paused';
                        motionBadge.className = 'badge status-pill bg-secondary';
                    } else if (camState === 'reconnecting') {
                        motionBadge.textContent = 'Camera: Reconnecting...';
                        motionBadge.className = 'badge status-pill bg-warning text-dark';
                        if (this.lastCameraState !== 'reconnecting') {
                            this.announce('Camera reconnecting.');
                        }
                    } else if (isMoving) {
                        motionBadge.textContent = 'Camera: Moving (Hold steady)';
                        motionBadge.className = 'badge status-pill bg-warning text-dark';
                        if (this.lastMovingState !== true) {
                            this.announce('Camera is moving. Hold steady.');
                        }
                    } else {
                        motionBadge.textContent = 'Camera: Steady';
                        motionBadge.className = 'badge status-pill bg-success';
                        if (this.lastMovingState === true) {
                            this.announce('Camera steady.');
                        }
                    }
                }
                this.lastMovingState = isMoving;
                this.lastCameraState = camState;

                // Speech status
                const speechBadge = document.getElementById('speechBadge');
                const isSpeaking = pipe.audio ? pipe.audio.speaking : false;
                if (speechBadge) {
                    if (isSpeaking) {
                        speechBadge.textContent = 'Speech: Speaking';
                        speechBadge.className = 'badge status-pill bg-primary';
                    } else {
                        speechBadge.textContent = 'Speech: Ready';
                        speechBadge.className = 'badge status-pill bg-info text-dark';
                    }
                }
                this.lastSpeakingState = isSpeaking;

                // Viewfinder status overlay
                const statusOverlay = document.getElementById('cameraStatusOverlay');
                const pipelineDetails = document.getElementById('pipelineDetails');
                const outcome = pipe.last_outcome;
                const friendlyStatus = outcome ? outcome.replace(/_/g, ' ') : (this.isRunning ? 'Active' : 'Idle');

                if (statusOverlay) {
                    statusOverlay.textContent = this.isRunning ? (isMoving ? 'Moving' : 'Reading') : 'Ready';
                }

                if (pipelineDetails) {
                    if (!this.isRunning) {
                        pipelineDetails.textContent = 'Status: Paused. Press Space to resume.';
                    } else if (isMoving) {
                        pipelineDetails.textContent = 'Status: Camera moving... Hold steady over text.';
                    } else if (pipe.last_text) {
                        pipelineDetails.textContent = `Status: Reading recognized text (${pipe.frames_processed} frames evaluated).`;
                    } else {
                        pipelineDetails.textContent = 'Status: Camera steady. Searching for clear text.';
                    }
                }

                // Update text display & announce when new text is accepted
                const output = document.getElementById('ocrOutput');
                if (pipe.last_text) {
                    if (pipe.last_text !== this.lastTextSeen) {
                        this.lastTextSeen = pipe.last_text;
                        if (output) {
                            output.textContent = pipe.last_text;
                            output.classList.add('fade-in');
                            setTimeout(() => output.classList.remove('fade-in'), 300);
                        }
                        this.announce(`Text detected: ${pipe.last_text}`);
                    }
                } else if (this.isRunning && isMoving && output && output.textContent.includes('Waiting for text')) {
                    output.textContent = 'Camera is moving... Hold steady to read text.';
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
                if (list) list.innerHTML = '';
                if (count) count.textContent = String(data.history.length);
                
                data.history.forEach((h) => {
                    const item = document.createElement('div');
                    item.className = 'history-item';
                    
                    const time = new Date(h.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    const engine = h.engine ? ` [${h.engine}]` : '';
                    const conf = h.confidence ? ` ${(h.confidence * 100).toFixed(0)}%` : '';
                    
                    item.innerHTML = `
                        <div class="history-item-time">${time}${engine}${conf}</div>
                        <div class="history-item-text">${this.escapeHtml(h.text)}</div>
                    `;
                    if (list) list.appendChild(item);
                });
            } else {
                if (list) list.innerHTML = '<div class="text-muted text-center py-2">No history recorded yet</div>';
                if (count) count.textContent = '0';
            }
        } catch (error) {
            console.error('Error updating history:', error);
        }
    }

    updateStatusBadge(isRunning) {
        const badge = document.getElementById('statusBadge');
        if (badge) {
            if (isRunning) {
                badge.textContent = 'Running';
                badge.className = 'status-badge status-running';
            } else {
                badge.textContent = 'Paused';
                badge.className = 'status-badge status-stopped';
            }
        }
    }

    showAlert(type, message, isHtml = false) {
        const container = document.getElementById('alertContainer');
        if (!container) return;
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} fade show`;
        alert.setAttribute('role', 'status');
        
        if (isHtml) {
            alert.innerHTML = message;
        } else {
            alert.textContent = message;
        }
        
        container.innerHTML = '';
        container.appendChild(alert);
        
        const timeout = (type === 'danger' || type === 'warning') ? 10000 : 5000;
        setTimeout(() => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, timeout);
    }

    startPolling() {
        this.statusInterval = setInterval(() => this.updateStatus(), 1000);
        this.historyInterval = setInterval(() => this.updateHistory(), 3000);
        this.updateStatus();
        this.updateHistory();
    }

    stopPolling() {
        if (this.statusInterval) clearInterval(this.statusInterval);
        if (this.historyInterval) clearInterval(this.historyInterval);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export for Node unit tests
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Dashboard;
}
