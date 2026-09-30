// video.js — видеоголограмма: вертикальные 9:16 ролики с прозрачным фоном
// (VP9 WebM с альфой), по одному на состояние. Тот же API, что у HoloFigure,
// поэтому hologram.js не различает типы моделей.

const STATES = ['idle', 'listening', 'thinking', 'speaking'];

export class VideoFigure {
    constructor(container) {
        this.state = 'idle';
        this.visible = false;
        this._active = null;
        this.noVideo = false;

        this.root = document.createElement('div');
        this.root.className = 'holo-video-root';
        this.root.innerHTML = '<div class="holo-video-scan"></div>';
        container.appendChild(this.root);

        this._vid = {};
        for (const s of STATES) {
            const v = document.createElement('video');
            v.className = 'holo-video';
            v.muted = true;
            v.loop = true;
            v.playsInline = true;
            v.preload = 'auto';
            v.dataset.state = s;
            v.src = `/models/video/${s}.webm`;
            v.addEventListener('error', () => {
                if (s === 'idle') this.noVideo = true;
                else v.dataset.bad = '1';   // нет ролика состояния — возьмём idle
            });
            this.root.appendChild(v);
            this._vid[s] = v;
        }
    }

    _showOnly(name) {
        const target = (name !== 'idle' && this._vid[name]?.dataset.bad) ? 'idle' : name;
        STATES.forEach((k) => {
            const v = this._vid[k];
            const on = k === target && !v.dataset.bad;
            v.style.opacity = on ? 1 : 0;
            if (on) v.play().catch(() => {});
            else v.pause();
        });
        this._active = target;
    }

    async show() {
        this.visible = true;
        this.root.classList.add('active');
        this._showOnly(this.state);
    }

    async hide() {
        this.root.classList.remove('active');
        this.visible = false;
        STATES.forEach((k) => this._vid[k].pause());
    }

    setState(name) {
        this.state = name;
        if (this.visible) this._showOnly(name);
    }

    // амплитуда микрофона/речи — лёгкая пульсация свечения
    setAmp(v) {
        this.root.style.setProperty('--holo-amp', Math.max(0, Math.min(1, v)).toFixed(2));
    }

    glitch(strength = 1, ms = 200) {
        this.root.classList.add('glitch');
        setTimeout(() => this.root.classList.remove('glitch'), ms);
    }

    start() { /* видео крутится само */ }
    stop() { this.hide(); }
    resize() { /* CSS-раскладка */ }

    dispose() {
        STATES.forEach((k) => this._vid[k].pause());
        this.root.remove();
    }
}
