// Smart Vision Assist v2.0.4 — Dashboard JavaScript
// Redesigned UI wiring — all API logic preserved exactly.
// Audio-First, Accessible, Screen-Reader and Keyboard Enabled.

class Dashboard {
    constructor(config, voices, isCloud = false) {
        this.config   = config;
        this.voices   = voices;
        this.isCloud  = isCloud;        // true on Railway — use browser camera + Web Speech
        this.statusInterval  = null;
        this.historyInterval = null;
        this.isRunning = false;
        this.lastAnnouncement = '';
        this.lastTextSeen    = '';
        this.lastMovingState  = null;
        this.lastCameraState  = null;
        this.lastSpeakingState = null;
        this._cameraErrors   = 0;
        // Cloud-mode state
        this._browserStream  = null;    // MediaStream from getUserMedia
        this._frameTimer     = null;    // setInterval handle for frame capture
        this._speechSynth    = window.speechSynthesis || null;
        this._lastSpokenText = '';      // avoid re-speaking same phrase
    }

    init() {
        this.setupEventListeners();
        this.setupKeyboardShortcuts();
        this.updateRangeValues();
        this.loadConfig();
        this.startPolling();
        if (this.isCloud) {
            this._initBrowserCamera();
            this.announce('Smart Vision Assist ready. Press Start Reading to activate your camera.');
            this.showAlert('info', 'Cloud mode — your browser camera will be used. Press Start Reading.');
        } else {
            this.announce('Smart Vision Assist ready. Press Space or Start Reading to begin.');
            this.showAlert('info', 'Ready — press Start Reading or Space, then point the camera at text.');
        }
    }

    // ── Element helpers ──────────────────────────────────────
    el(id) { return document.getElementById(id); }

    // ── Event Listeners ──────────────────────────────────────
    setupEventListeners() {
        const startBtn      = this.el('startBtn');
        const stopBtn       = this.el('stopBtn');
        const replayBtn     = this.el('replayBtn');
        const stopSpeechBtn = this.el('stopSpeechBtn');
        const testCameraBtn = this.el('testCameraBtn');
        const testOcrBtn    = this.el('testOcrBtn');

        if (startBtn)      startBtn.addEventListener('click',      () => this.startPipeline());
        if (stopBtn)       stopBtn.addEventListener('click',       () => this.stopPipeline());
        if (replayBtn)     replayBtn.addEventListener('click',     () => this.replayAudio());
        if (stopSpeechBtn) stopSpeechBtn.addEventListener('click', () => this.stopSpeech());
        if (testCameraBtn) testCameraBtn.addEventListener('click', () => this.testCamera());
        if (testOcrBtn)    testOcrBtn.addEventListener('click',    () => this.testOCR());

        // Settings form submissions
        const ocrForm    = this.el('ocrForm');
        const ttsForm    = this.el('ttsForm');
        const cameraForm = this.el('cameraForm');
        if (ocrForm)    ocrForm.addEventListener('submit',    (e) => this.saveOCRConfig(e));
        if (ttsForm)    ttsForm.addEventListener('submit',    (e) => this.saveTTSConfig(e));
        if (cameraForm) cameraForm.addEventListener('submit', (e) => this.saveCameraConfig(e));

        // Range slider live display
        const ranges = [
            ['captureInterval', 'captureIntervalValue', 1],
            ['minConfidence',   'minConfidenceValue',   2],
            ['minTextLen',      'minTextLenValue',      0],
            ['ttsSpeed',        'ttsSpeedValue',        1],
            ['ttsVolume',       'ttsVolumeValue',       1],
        ];
        ranges.forEach(([inputId, valId, decimals]) => {
            const input = this.el(inputId);
            const span  = this.el(valId);
            if (input && span) {
                input.addEventListener('input', (e) => {
                    const n = parseFloat(e.target.value);
                    span.textContent = decimals > 0 ? n.toFixed(decimals) : String(parseInt(n, 10));
                });
            }
        });
    }

    // ── Keyboard Shortcuts ───────────────────────────────────
    setupKeyboardShortcuts() {
        window.addEventListener('keydown', (e) => {
            // Never intercept typing in inputs / selects / textareas / contenteditable
            if (e.target && (e.target.matches('input, select, textarea') || e.target.isContentEditable)) {
                return;
            }
            if (e.code === 'Space') {
                e.preventDefault();
                this.isRunning ? this.stopPipeline() : this.startPipeline();
            } else if (e.key === 'r' || e.key === 'R') {
                e.preventDefault();
                this.replayAudio();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.stopSpeech();
            }
        });
    }

    // ── Screen Reader Announcements ──────────────────────────
    announce(text) {
        const sr = this.el('srLiveAnnouncements');
        if (!sr || !text || text === this.lastAnnouncement) return;
        this.lastAnnouncement = text;
        sr.textContent = '';
        setTimeout(() => { sr.textContent = text; }, 50);
    }

    // ── Range Value Init ─────────────────────────────────────
    updateRangeValues() {
        [
            ['captureInterval', 'captureIntervalValue', 1],
            ['minConfidence',   'minConfidenceValue',   2],
            ['minTextLen',      'minTextLenValue',      0],
            ['ttsSpeed',        'ttsSpeedValue',        1],
            ['ttsVolume',       'ttsVolumeValue',       1],
        ].forEach(([inputId, valId, decimals]) => {
            const input = this.el(inputId);
            const span  = this.el(valId);
            if (input && span) {
                const n = parseFloat(input.value);
                span.textContent = decimals > 0 ? n.toFixed(decimals) : String(parseInt(n, 10));
            }
        });
    }

    // ── Load Config into Forms ───────────────────────────────
    loadConfig() {
        if (this.config.ocr) {
            const ocr = this.config.ocr;
            const set = (id, v) => { const el = this.el(id); if (el) el.value = v; };
            set('ocrEngine',       ocr.engine           || 'easyocr');
            set('ocrLang',         ocr.language          || 'en');
            set('ocrMode',         ocr.mode              || 'fallback');
            set('captureInterval', ocr.capture_interval  || 0.5);
            set('minConfidence',   ocr.min_confidence    || 0.5);
            set('minTextLen',      ocr.min_text_len      || 3);
        }
        if (this.config.tts) {
            const tts = this.config.tts;
            const set = (id, v) => { const el = this.el(id); if (el) el.value = v; };
            set('ttsEngine', tts.engine || 'coqui');
            set('ttsVoice',  tts.voice  || 'p335');
            set('ttsSpeed',  tts.speed  || 1.0);
            set('ttsVolume', tts.volume || 0.9);
        }
        if (this.config.camera) {
            const cam = this.config.camera;
            const set = (id, v) => { const el = this.el(id); if (el) el.value = v; };
            set('cameraSource', cam.source_type || 'opencv');
            set('cameraId',     cam.camera_id   || 0);
            set('resolution',   cam.resolution  || '720p');
        }
        this.updateRangeValues();
    }

    // ── Browser Camera (Cloud / Railway mode) ────────────────
    async _initBrowserCamera() {
        const video  = this.el('browserCamera');
        const offline = this.el('cameraOfflineState');
        if (!video) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 480 } },
                audio: false
            });
            this._browserStream = stream;
            video.srcObject = stream;
            this.setCameraOffline(false);
            this.setCameraStatePill('active', 'Browser camera');
            this.el('cameraOverlayText') && (this.el('cameraOverlayText').textContent = 'Position text inside the frame');
        } catch (err) {
            const msg = err.name === 'NotAllowedError'
                ? 'Camera permission denied — allow camera access in your browser.'
                : `Camera unavailable: ${err.message}`;
            this.setCameraOffline(true, 'Camera unavailable', msg);
            this.showAlert('danger', msg);
            this.announce(msg);
        }
    }

    _startFrameCapture() {
        if (this._frameTimer) return;  // already running
        const video  = this.el('browserCamera');
        const canvas = this.el('frameCanvas');
        if (!video || !canvas) return;
        const interval = (this.config.ocr && this.config.ocr.capture_interval)
            ? Math.max(1000, this.config.ocr.capture_interval * 1000)
            : 1500;
        this._frameTimer = setInterval(async () => {
            if (!this.isRunning || !video.readyState || video.readyState < 2) return;
            canvas.width  = video.videoWidth  || 640;
            canvas.height = video.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
            try {
                const resp = await fetch('/api/process-frame', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: dataUrl })
                });
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.text && data.text !== this.lastTextSeen) {
                    this.lastTextSeen = data.text;
                    this._showDetectedText(data.text);
                    this.setTextState('detected', 'Detected');
                    this._speakBrowser(data.text);
                    this.announce(`Text detected: ${data.text}`);
                    // Update history via server
                    this.updateHistory();
                }
            } catch (_) { /* network hiccup — next tick */ }
        }, interval);
    }

    _stopFrameCapture() {
        if (this._frameTimer) { clearInterval(this._frameTimer); this._frameTimer = null; }
    }

    _speakBrowser(text) {
        if (!this._speechSynth || !text) return;
        if (text === this._lastSpokenText) return;  // don't repeat
        this._lastSpokenText = text;
        this._speechSynth.cancel();  // stop any current speech
        const utt = new SpeechSynthesisUtterance(text);
        utt.lang  = 'en-US';
        utt.rate  = (this.config.tts && this.config.tts.speed) || 1.0;
        utt.volume = (this.config.tts && this.config.tts.volume) || 0.9;
        utt.onstart = () => this.setTextState('speaking', 'Speaking');
        utt.onend   = () => this.setTextState('detected', 'Detected');
        this._speechSynth.speak(utt);
    }

    // ── Pipeline Controls ────────────────────────────────────
    async startPipeline() {
        const btn = this.el('startBtn');
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span><span>Starting…</span>'; }
        try {
            if (this.isCloud) {
                // Cloud: ensure browser camera is active, start frame-capture loop
                if (!this._browserStream || !this._browserStream.active) {
                    await this._initBrowserCamera();
                }
                this.isRunning = true;
                this._startFrameCapture();
                this.setSystemStatus('reading', 'Reading');
                this.updateActionButtons();
                this.setActionHint('Hold text steady in front of your camera.');
                this.announce('Reading started. Point your camera at text.');
                this.showAlert('success', 'Reading started — point your camera at text.');
                // Also notify server (for status tracking)
                fetch('/api/start', { method: 'POST' }).catch(() => {});
            } else {
                // Local: server controls the physical camera
                const resp = await fetch('/api/start', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'started') {
                    this.isRunning = true;
                    this.setSystemStatus('reading', 'Reading');
                    this.updateActionButtons();
                    this.setActionHint('Camera active — point at text to begin reading.');
                    this.announce('System started. Camera active. Point camera at text.');
                    this.showAlert('success', 'Reading started — point the camera at text.');
                } else {
                    this.showAlert('danger', 'Could not start the reading system.');
                }
            }
        } catch (err) {
            this.showAlert('danger', `Error starting: ${err.message}`);
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><span class="btn-text">Start Reading</span><kbd class="btn-kbd">Space</kbd>'; }
        }
    }

    async stopPipeline() {
        if (this.isCloud) {
            this.isRunning = false;
            this._stopFrameCapture();
            if (this._speechSynth) this._speechSynth.pause();
            this.setSystemStatus('paused', 'Paused');
            this.updateActionButtons();
            this.setActionHint('Paused — press Start Reading to resume.');
            this.announce('Paused.');
            this.showAlert('info', 'Paused.');
            fetch('/api/stop', { method: 'POST' }).catch(() => {});
        } else {
            try {
                const resp = await fetch('/api/stop', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'stopped') {
                    this.isRunning = false;
                    this.setSystemStatus('paused', 'Paused');
                    this.updateActionButtons();
                    this.setActionHint('Reading paused — press Start Reading or Space to resume.');
                    this.announce('System paused.');
                    this.showAlert('info', 'Paused.');
                }
            } catch (err) {
                this.showAlert('danger', `Error pausing: ${err.message}`);
            }
        }
    }

    async stopSpeech() {
        if (this.isCloud && this._speechSynth) {
            this._speechSynth.cancel();
            this._lastSpokenText = '';
            this.setTextState('idle', 'Idle');
            this.announce('Speech stopped.');
            this.showAlert('info', 'Speech stopped.');
        } else {
            try {
                const resp = await fetch('/api/stop-speech', { method: 'POST' });
                if (resp.ok) {
                    this.announce('Speech stopped.');
                    this.setTextState('idle', 'Idle');
                    this.showAlert('info', 'Speech stopped.');
                }
            } catch (err) {
                this.showAlert('warning', `Could not stop speech: ${err.message}`);
            }
        }
    }

    async replayAudio() {
        if (this.isCloud) {
            // Replay last detected text using Web Speech API
            if (this.lastTextSeen) {
                this._lastSpokenText = '';  // allow replay
                this._speakBrowser(this.lastTextSeen);
                this.announce(`Replaying: ${this.lastTextSeen.substring(0, 60)}`);
                this.showAlert('success', 'Replaying…');
            } else {
                this.announce('No text to replay yet.');
                this.showAlert('warning', 'No recognized text available to replay.');
            }
            return;
        }
        try {
            // Try WAV replay first (Coqui TTS stores audio)
            const resp = await fetch('/api/replay');
            if (resp.status === 200) {
                const blob = await resp.blob();
                const url  = URL.createObjectURL(blob);
                new Audio(url).play();
                this.announce('Replaying latest audio.');
                this.showAlert('success', 'Replaying audio…');
                return;
            }
            // Fallback: re-speak through server TTS
            const fb   = await fetch('/api/replay-latest', { method: 'POST' });
            const data = await fb.json();
            if (fb.ok && data.status === 'replaying') {
                this.announce(`Replaying: ${data.text.substring(0, 60)}`);
                this.showAlert('success', 'Replaying text…');
            } else {
                this.announce('No text to replay yet.');
                this.showAlert('warning', data.message || 'No recognized text available to replay.');
            }
        } catch (err) {
            this.showAlert('danger', `Replay error: ${err.message}`);
        }
    }

    // ── Diagnostics ──────────────────────────────────────────
    async testCamera() {
        const btn = this.el('testCameraBtn');
        if (!btn) return;
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner dark"></span> Testing…';
        try {
            const resp = await fetch('/api/test-camera');
            const data = await resp.json();
            if (data.status === 'ok') {
                const res = data.frame_shape ? `${data.frame_shape[1]}×${data.frame_shape[0]}` : '';
                this.announce(`Camera working. Resolution ${res}.`);
                this.showAlert('success', `Camera OK — ${res}`);
            } else {
                const msg = data.message ? this.humanizeError(data.message) : 'Camera unavailable';
                this.announce(`Camera test failed: ${msg}`);
                this.showAlert('danger', `Camera: ${msg}`);
            }
        } catch (err) {
            this.showAlert('danger', `Camera test error: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = orig;
        }
    }

    async testOCR() {
        const btn = this.el('testOcrBtn');
        if (!btn) return;
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner dark"></span> Running…';
        try {
            const resp = await fetch('/api/test-ocr');
            const data = await resp.json();
            if (data.status === 'ok') {
                this.showAlert('info', Dashboard.formatOcrTest(data), true);
                if (data.ocr_test_on_frame && data.ocr_test_on_frame.text) {
                    this.announce(`OCR test read: ${data.ocr_test_on_frame.text}`);
                }
            } else {
                this.showAlert('danger', `OCR error: ${this.escapeHtml(data.message || data.detail || 'Unknown')}`);
            }
        } catch (err) {
            this.showAlert('danger', `OCR diagnostic error: ${this.escapeHtml(err.message)}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = orig;
        }
    }

    humanizeError(raw) {
        if (!raw) return 'System unavailable';
        const lo = String(raw).toLowerCase();
        if (lo.includes('cannot open camera') || lo.includes('cap_dshow') || lo.includes('no frame')) {
            return 'Camera unavailable — check that your webcam is plugged in and not in use by another app.';
        }
        if (lo.includes('timeout')) return 'Processing timed out. Hold the document steady.';
        return raw;
    }

    /** HTML for a /api/test-ocr response. Pure (no DOM) — unit-tested under Node.
     *  All server-provided text (including OCR output) is escaped. */
    static formatOcrTest(data) {
        const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
            (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const pct = (x) => `${(Number(x) * 100).toFixed(1)}%`;
        const cfg = data.config || {};
        const ocrEngines = data.ocr_engines || {};
        const engineList = (engines) => {
            let html = '';
            for (const [engine, d] of Object.entries(engines || {})) {
                let icon = '❌', label = d.status;
                if (d.status === 'READY') icon = '✅';
                else if (d.status === 'DISABLED') icon = '⏸️';
                else if (d.status === 'UNINITIALIZED') { icon = '⏳'; label = 'not loaded yet'; }
                html += `${icon} ${esc(engine)}: ${esc(label)}`;
                if (!['READY', 'UNINITIALIZED'].includes(d.status) && d.detail) {
                    html += `<br><small style="color:#666">${esc(d.detail)}</small>`;
                }
                html += '<br>';
            }
            return html;
        };
        const REASONS = {
            no_text: 'no text found in frame',
            below_min_confidence: 'text found but confidence too low',
            below_threshold: 'text rejected by quality scoring',
            no_engine_available: 'no OCR engine is available',
            all_engines_failed: 'every OCR engine failed',
        };
        let msg = '<strong>OCR Engines:</strong><br>' + engineList(ocrEngines);
        msg += '<br><strong>Speech Engines:</strong><br>' + engineList(data.tts_engines);
        const r = data.ocr_test_on_frame;
        if (r) {
            msg += '<br><strong>Frame OCR Test:</strong> ';
            if (r.error) {
                msg += `❌ No usable camera frame: ${esc(r.error)}`;
            } else if (r.text) {
                msg += `✅ Read: "${esc(r.text.substring(0, 60))}"`;
                msg += `<br>Engine: ${esc(r.engine)}, Confidence: ${pct(r.confidence)}, Score: ${pct(r.score)}`;
            } else {
                msg += `⚠️ ${esc(REASONS[r.reason] || r.reason)}`;
                for (const [eng, conf] of Object.entries(r.low_confidence || {})) {
                    msg += `<br>${esc(eng)} confidence ${pct(conf)} &lt; minimum ${pct(cfg.min_confidence)}`;
                }
                for (const c of r.candidates || []) {
                    msg += `<br>${esc(c.engine)} read "${esc(c.text.substring(0, 50))}" score ${pct(c.score)}`;
                }
                for (const [eng, code] of Object.entries(r.errors || {})) {
                    msg += `<br>${esc(eng)} error: ${esc(code)}`;
                }
            }
            if (r.engines_run && r.engines_run.length) {
                msg += `<br>Engines tried: ${esc(r.engines_run.join(', '))}`;
            }
            if (r.frame) msg += `<br>Frame: ${esc(r.frame.shape.join('×'))}, brightness ${esc(r.frame.mean)}`;
            if (r.latency_s !== undefined) msg += `, OCR time ${esc(r.latency_s)}s`;
        }
        msg += `<br><br><strong>Config:</strong> Mode=${esc(cfg.mode)}, Engine=${esc(cfg.engine)}, Min confidence=${esc(cfg.min_confidence)}`;
        return msg;
    }

    configError(data, what) {
        const details = (data.errors || []).join('; ');
        this.showAlert('danger', `Could not save ${what}${details ? ': ' + details : ''}`);
    }

    // ── Config Save ──────────────────────────────────────────
    async saveOCRConfig(e) {
        e.preventDefault();
        const btn = this.el('saveOcr');
        await this._saveConfig(btn, 'recognition settings', {
            ocr: {
                engine:           this.el('ocrEngine').value,
                language:         this.el('ocrLang').value,
                capture_interval: parseFloat(this.el('captureInterval').value),
                min_confidence:   parseFloat(this.el('minConfidence').value),
                min_text_len:     parseInt(this.el('minTextLen').value, 10),
                mode:             this.el('ocrMode').value,
            }
        });
    }

    async saveTTSConfig(e) {
        e.preventDefault();
        const btn = this.el('saveTts');
        await this._saveConfig(btn, 'speech settings', {
            tts: {
                engine: this.el('ttsEngine').value,
                voice:  this.el('ttsVoice').value,
                speed:  parseFloat(this.el('ttsSpeed').value),
                volume: parseFloat(this.el('ttsVolume').value),
            }
        });
    }

    async saveCameraConfig(e) {
        e.preventDefault();
        const btn = this.el('saveCamera');
        await this._saveConfig(btn, 'camera settings', {
            camera: {
                source_type: this.el('cameraSource').value,
                camera_id:   parseInt(this.el('cameraId').value, 10),
                resolution:  this.el('resolution').value,
            }
        });
    }

    async _saveConfig(btn, label, payload) {
        const orig = btn ? btn.innerHTML : '';
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Saving…'; }
        try {
            const resp = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (data.status === 'saved') {
                Object.assign(this.config, payload);
                this.showAlert('success', `Saved ${label}.`);
            } else {
                this.configError(data, label);
            }
        } catch (err) {
            this.showAlert('danger', `Error saving ${label}: ${err.message}`);
        } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = orig; }
        }
    }

    // ── Camera Snapshot Refresh ──────────────────────────────
    async refreshCameraPreview() {
        const img = this.el('cameraPreview');
        if (!img) return;
        const newImg = new Image();
        newImg.onload = () => {
            img.src = newImg.src;
            img.classList.remove('dim');
            this._cameraErrors = 0;
            this.setCameraOffline(false);
        };
        newImg.onerror = () => {
            this._cameraErrors++;
            img.classList.add('dim');
            if (this._cameraErrors >= 3) {
                this.setCameraOffline(true, 'Camera unavailable', 'Check that your camera is connected.');
            }
        };
        newImg.src = `/api/camera/snapshot?t=${Date.now()}`;
    }

    setCameraOffline(visible, title = 'Camera unavailable', msg = '') {
        const el = this.el('cameraOfflineState');
        const t  = this.el('cameraOfflineTitle');
        const m  = this.el('cameraOfflineMsg');
        if (!el) return;
        el.classList.toggle('visible', visible);
        if (t && title) t.textContent = title;
        if (m && msg)   m.textContent = msg;
    }

    // ── Status Updates ───────────────────────────────────────
    async updateStatus() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            if (!data.pipeline) return;
            const pipe = data.pipeline;

            this.isRunning = pipe.running || false;

            // Refresh server camera snapshot (local mode only — cloud uses browser video stream)
            if (this.isRunning && !this.isCloud) this.refreshCameraPreview();

            const camState = pipe.camera  ? pipe.camera.state       : 'stopped';
            const isMoving = pipe.motion  ? pipe.motion.is_moving   : false;
            const isSpeaking = pipe.audio ? pipe.audio.speaking     : false;

            // ── System status dot + text ──────────────────────
            if (!this.isRunning) {
                this.setSystemStatus('paused', 'Paused');
            } else if (camState === 'reconnecting') {
                this.setSystemStatus('paused', 'Reconnecting…');
                if (this.lastCameraState !== 'reconnecting') this.announce('Camera reconnecting.');
                this.setCameraStatePill('moving', 'Reconnecting…');
            } else if (isMoving) {
                this.setSystemStatus('reading', 'Reading');
                this.setCameraStatePill('moving', 'Hold steady');
                if (this.lastMovingState !== true) this.announce('Camera moving — hold steady.');
            } else {
                this.setSystemStatus('reading', 'Reading');
                this.setCameraStatePill('active', 'Active');
                if (this.lastMovingState === true) this.announce('Camera steady.');
            }
            this.lastMovingState  = isMoving;
            this.lastCameraState  = camState;

            // ── Camera overlay text ───────────────────────────
            const overlayText = this.el('cameraOverlayText');
            if (overlayText) {
                if (!this.isRunning) {
                    overlayText.textContent = 'Position text inside the frame';
                } else if (isMoving) {
                    overlayText.textContent = 'Hold steady…';
                } else {
                    overlayText.textContent = pipe.last_text ? 'Text detected' : 'Reading…';
                }
            }

            // ── Text state pill + speech state ────────────────
            if (isSpeaking) {
                this.setTextState('speaking', 'Speaking');
                if (this.lastSpeakingState !== true) this.announce('Speaking detected text.');
            } else if (pipe.last_text) {
                this.setTextState('detected', 'Detected');
            } else {
                this.setTextState('idle', 'Idle');
            }
            this.lastSpeakingState = isSpeaking;

            // ── Pipeline hint text ────────────────────────────
            const details = this.el('pipelineDetails');
            if (details) {
                if (!this.isRunning) {
                    details.textContent = 'Press Start to begin reading';
                } else if (isMoving) {
                    details.textContent = 'Hold steady over the text';
                } else if (pipe.last_text) {
                    details.textContent = `${pipe.frames_processed || ''} frames evaluated`.trim();
                } else {
                    details.textContent = 'Searching for text…';
                }
            }

            // ── OCR Output ────────────────────────────────────
            if (pipe.last_text && pipe.last_text !== this.lastTextSeen) {
                this.lastTextSeen = pipe.last_text;
                this._showDetectedText(pipe.last_text);
                this.announce(`Text detected: ${pipe.last_text}`);
            } else if (this.isRunning && isMoving && this.lastTextSeen === '') {
                this._showPlaceholder('moving');
            }

            this.updateActionButtons();
        } catch (err) {
            console.error('Status poll error:', err);
        }
    }

    _showDetectedText(text) {
        const output = this.el('ocrOutput');
        if (!output) return;
        // Clear placeholder, show text
        output.innerHTML = '';
        const p = document.createElement('div');
        p.className = 'ocr-text-new';
        p.textContent = text;
        p.style.cssText = 'font-size:var(--text-ocr);line-height:1.7;font-weight:400;color:var(--text);white-space:pre-wrap;word-break:break-word;';
        output.appendChild(p);
    }

    _showPlaceholder(state = 'idle') {
        const output = this.el('ocrOutput');
        if (!output) return;
        // Only update placeholder if we haven't shown real text yet
        if (this.lastTextSeen) return;
        const icons   = { idle: '📖', moving: '📖', processing: '📖' };
        const titles  = { idle: 'Ready to read', moving: 'Hold steady…', processing: 'Looking for text…' };
        const descs   = {
            idle:       'Point the camera at printed or handwritten text to begin.',
            moving:     'Keep the camera still and the page flat.',
            processing: 'The camera is reading — results appear here.',
        };
        output.innerHTML = `
          <div class="ocr-placeholder">
            <div class="ocr-placeholder-icon" aria-hidden="true">${icons[state]}</div>
            <div class="ocr-placeholder-title">${titles[state]}</div>
            <div class="ocr-placeholder-msg">${descs[state]}</div>
          </div>`;
    }

    // ── History ──────────────────────────────────────────────
    async updateHistory() {
        try {
            const resp = await fetch('/api/history');
            const data = await resp.json();
            const list  = this.el('historyList');
            const count = this.el('historyCount');
            if (!list) return;

            if (data.history && data.history.length > 0) {
                list.innerHTML = '';
                if (count) count.textContent = `${data.history.length} item${data.history.length !== 1 ? 's' : ''}`;
                data.history.forEach((h) => {
                    const item = document.createElement('div');
                    item.className = 'history-item';
                    const time   = new Date(h.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    const engine = h.engine ? ` · ${h.engine}` : '';
                    const conf   = h.confidence ? ` · ${(h.confidence * 100).toFixed(0)}%` : '';
                    item.innerHTML = `
                      <div class="history-meta">${time}${engine}${conf}</div>
                      <div class="history-text">${this.escapeHtml(h.text)}</div>`;
                    list.appendChild(item);
                });
            } else {
                list.innerHTML = '<div class="history-empty">No recent readings yet</div>';
                if (count) count.textContent = '0 items';
            }
        } catch (err) {
            console.error('History poll error:', err);
        }
    }

    // ── UI State Helpers ─────────────────────────────────────
    setSystemStatus(state, label) {
        const dot  = this.el('statusDot');
        const text = this.el('statusText');
        if (dot)  { dot.className  = `status-dot ${state}`; }
        if (text) { text.textContent = label; }
    }

    setCameraStatePill(cls, label) {
        const pill = this.el('cameraStatePill');
        if (!pill) return;
        pill.className   = `camera-state-pill${cls ? ' ' + cls : ''}`;
        pill.textContent = label;
    }

    setTextState(cls, label) {
        const pill = this.el('textStatePill');
        if (!pill) return;
        pill.className   = `text-state-pill${cls ? ' ' + cls : ''}`;
        pill.textContent = label;
    }

    setActionHint(text) {
        const hint = this.el('actionHintText');
        if (hint) hint.textContent = text;
    }

    updateActionButtons() {
        const startBtn = this.el('startBtn');
        const stopBtn  = this.el('stopBtn');
        if (startBtn) {
            if (this.isRunning) {
                startBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><span class="btn-text">Reading…</span>';
                startBtn.style.opacity = '0.6';
            } else {
                startBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg><span class="btn-text">Start Reading</span><kbd class="btn-kbd">Space</kbd>';
                startBtn.style.opacity = '1';
            }
        }
        if (stopBtn) {
            stopBtn.disabled = !this.isRunning;
        }
    }

    // ── Alerts ───────────────────────────────────────────────
    showAlert(type, message, isHtml = false) {
        const container = this.el('alertContainer');
        if (!container) return;
        const div = document.createElement('div');
        div.className = `sva-alert ${type}`;
        div.setAttribute('role', 'status');
        if (isHtml) div.innerHTML  = message;
        else        div.textContent = message;
        container.innerHTML = '';
        container.appendChild(div);
        const timeout = (type === 'danger' || type === 'warning') ? 10000 : 5000;
        setTimeout(() => {
            div.style.transition = 'opacity 0.3s';
            div.style.opacity    = '0';
            setTimeout(() => div.remove(), 320);
        }, timeout);
    }

    // ── Polling ──────────────────────────────────────────────
    startPolling() {
        this.statusInterval  = setInterval(() => this.updateStatus(),  1000);
        this.historyInterval = setInterval(() => this.updateHistory(), 3000);
        this.updateStatus();
        this.updateHistory();
    }

    stopPolling() {
        if (this.statusInterval)  clearInterval(this.statusInterval);
        if (this.historyInterval) clearInterval(this.historyInterval);
    }

    // ── Utility ──────────────────────────────────────────────
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
