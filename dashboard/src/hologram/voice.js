// voice.js — голосовой контур голограммы: wake word «Джарвис», STT,
// амплитуда микрофона, воспроизведение TTS (сервер /voice/tts → браузер → тишина).
// Урок jarvis-репо: SpeechRecognition гаснет сам — рестартуем (heartbeat).

import { API_BASE } from '../apiClient.js';

const SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
// распознавание может коверкать слово — ловим варианты
const WAKE_RE = /дж?[ае]рв[ие]с/i;

export class VoiceIO {
    constructor({ onAmp } = {}) {
        this.onAmp = onAmp || (() => {});
        this.audioCtx = null;
        this.analyser = null;
        this.micStream = null;
        this._ampTimer = null;
        this._ampMax = 0.15;

        this.wakeOn = false;
        this._wakeRec = null;
        this._wakeRestart = null;
        this._wakeCb = null;
        this._wakeSpoken = false;
    }

    get sttAvailable() {
        return !!SR;
    }

    // ---------- микрофон + амплитуда ----------

    async ensureMic() {
        if (this.micStream) return true;
        try {
            this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            console.warn('[holo] микрофон недоступен:', e?.name || e);
            return false;
        }
        const AC = window.AudioContext || window.webkitAudioContext;
        this.audioCtx = this.audioCtx || new AC();
        if (this.audioCtx.state === 'suspended') {
            try { await this.audioCtx.resume(); } catch (e) {}
        }
        const src = this.audioCtx.createMediaStreamSource(this.micStream);
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 512;
        this.analyser.smoothingTimeConstant = 0.7;
        src.connect(this.analyser);
        this._startAmpLoop();
        return true;
    }

    _startAmpLoop() {
        if (this._ampTimer) return;
        const buf = new Uint8Array(this.analyser.fftSize);
        this._ampTimer = setInterval(() => {
            if (!this.analyser) return;
            this.analyser.getByteTimeDomainData(buf);
            let sum = 0;
            for (let i = 0; i < buf.length; i++) {
                const v = (buf[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / buf.length);
            if (rms > this._ampMax) this._ampMax = rms;          // бегущая нормировка
            this._ampMax = Math.max(0.06, this._ampMax * 0.999); // потолок медленно опускается
            this.onAmp(Math.min(1, rms / this._ampMax));
        }, 90);
    }

    stopAmpLoop() {
        clearInterval(this._ampTimer);
        this._ampTimer = null;
    }

    // ---------- wake word ----------

    startWake(onWake) {
        if (!SR || this.wakeOn) return;
        this.wakeOn = true;
        this._wakeCb = onWake;
        this._spawnWakeRec();
    }

    _spawnWakeRec() {
        if (!this.wakeOn || !SR) return;
        const rec = new SR();
        rec.lang = 'ru-RU';
        rec.continuous = true;
        rec.interimResults = true;
        rec.onresult = (ev) => {
            let heard = '';
            for (let i = ev.resultIndex; i < ev.results.length; i++) {
                heard += ev.results[i][0].transcript + ' ';
            }
            const m = heard.match(WAKE_RE);
            if (m && !this._wakeSpoken) {
                this._wakeSpoken = true;
                // остаток фразы после слова — сразу команда
                const rest = heard.slice(m.index + m[0].length).replace(/^[,!.?\s]+/, '').trim();
                setTimeout(() => (this._wakeSpoken = false), 4000);
                if (this._wakeCb) this._wakeCb(rest);
            }
        };
        rec.onerror = (ev) => {
            if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
                this.wakeOn = false; // микрофон запрещён — wake больше не поднимаем
                console.warn('[holo] STT недоступен:', ev.error);
            }
        };
        rec.onend = () => {
            // heartbeat: движок гаснет после паузы — перезапуск
            if (this.wakeOn) {
                this._wakeRestart = setTimeout(() => this._spawnWakeRec(), 350);
            }
        };
        this._wakeRec = rec;
        try { rec.start(); } catch (e) { /* уже запущен — игнорируем */ }
    }

    stopWake() {
        this.wakeOn = false;
        clearTimeout(this._wakeRestart);
        if (this._wakeRec) {
            this._wakeRec.onend = null;
            try { this._wakeRec.stop(); } catch (e) {}
            this._wakeRec = null;
        }
    }

    // ---------- разовая команда ----------

    /**
     * Слушаем одну реплику. resolve(text|null).
     * Тишина после слов 2.6 с или общий лимит 10 с — завершаем.
     */
    listenOnce({ onPartial } = {}) {
        return new Promise((resolve) => {
            if (!SR) return resolve(null);
            const rec = new SR();
            rec.lang = 'ru-RU';
            rec.continuous = false;
            rec.interimResults = true;

            let interim = '';
            let lastChange = performance.now();
            let done = false;
            let silenceT = null;
            let limitT = null;

            const finish = (text) => {
                if (done) return;
                done = true;
                clearTimeout(silenceT);
                clearTimeout(limitT);
                rec.onend = rec.onresult = rec.onerror = null;
                try { rec.stop(); } catch (e) {}
                resolve(text && text.trim() ? text.trim() : null);
            };
            const armSilence = () => {
                clearTimeout(silenceT);
                silenceT = setTimeout(() => finish(interim), 2600);
            };

            rec.onresult = (ev) => {
                let fin = '';
                interim = '';
                for (let i = 0; i < ev.results.length; i++) {
                    const r = ev.results[i];
                    if (r.isFinal) fin += r[0].transcript;
                    else interim += r[0].transcript;
                }
                lastChange = performance.now();
                if (onPartial) onPartial(fin || interim);
                if (fin.trim()) finish(fin);
                else armSilence();
            };
            rec.onerror = () => finish(null);
            rec.onend = () => finish(interim);
            limitT = setTimeout(() => finish(interim), 10000);

            try { rec.start(); armSilence(); } catch (e) { resolve(null); }
        });
    }

    // ---------- TTS ----------

    /**
     * Проговорить текст. Сервер /api/voice/tts (ElevenLabs/edge-tts) →
     * браузерный speechSynthesis → отказ (остаются субтитры).
     * Возвращает 'server' | 'browser' | 'none'.
     */
    async speak(text, { onAmp, onEnd } = {}) {
        const src = await this._speakServer(text, { onAmp });
        if (src) { if (onEnd) onEnd(src); return src; }
        const b = await this._speakBrowser(text, { onAmp });
        if (onEnd) onEnd(b);
        return b;
    }

    async _speakServer(text, { onAmp }) {
        try {
            const res = await fetch(`${API_BASE}/voice/tts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            const ctype = res.headers.get('content-type') || '';
            if (!res.ok || !ctype.startsWith('audio/')) return null;

            const buf = await res.arrayBuffer();
            const AC = window.AudioContext || window.webkitAudioContext;
            this.audioCtx = this.audioCtx || new AC();
            if (this.audioCtx.state === 'suspended') {
                try { await this.audioCtx.resume(); } catch (e) {}
            }
            const audio = await this.audioCtx.decodeAudioData(buf);
            return await new Promise((resolve) => {
                const srcNode = this.audioCtx.createBufferSource();
                srcNode.buffer = audio;
                const gain = this.audioCtx.createGain();
                gain.gain.value = 0.95;
                const analyser = this.audioCtx.createAnalyser();
                analyser.fftSize = 512;
                srcNode.connect(gain);
                gain.connect(analyser);
                analyser.connect(this.audioCtx.destination);

                const abuf = new Uint8Array(analyser.fftSize);
                let t = null;
                srcNode.onended = () => {
                    clearInterval(t);
                    onAmp?.(0);
                    resolve('server');
                };
                t = setInterval(() => {
                    analyser.getByteTimeDomainData(abuf);
                    let sum = 0;
                    for (let i = 0; i < abuf.length; i++) {
                        const v = (abuf[i] - 128) / 128;
                        sum += v * v;
                    }
                    onAmp?.(Math.min(1, Math.sqrt(sum / abuf.length) * 5));
                }, 90);
                srcNode.start();
            });
        } catch (e) {
            console.warn('[holo] серверный TTS недоступен, фолбэк:', e?.message || e);
            return null;
        }
    }

    _speakBrowser(text, { onAmp }) {
        return new Promise((resolve) => {
            if (!('speechSynthesis' in window)) return resolve('none');
            try {
                const u = new SpeechSynthesisUtterance(text);
                const voices = speechSynthesis.getVoices();
                const ru = voices.find((v) => v.lang?.toLowerCase().startsWith('ru'));
                if (ru) u.voice = ru;
                u.lang = ru?.lang || 'ru-RU';
                u.rate = 1.03;
                u.pitch = 1.05;
                let ampT = null;
                u.onstart = () => {
                    ampT = setInterval(() => onAmp?.(0.25 + Math.random() * 0.5), 140);
                };
                u.onend = u.onerror = () => {
                    clearInterval(ampT);
                    onAmp?.(0);
                    resolve('browser');
                };
                speechSynthesis.speak(u);
            } catch (e) {
                resolve('none');
            }
        });
    }

    stopSpeaking() {
        try { speechSynthesis.cancel(); } catch (e) {}
    }
}
