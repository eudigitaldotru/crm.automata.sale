// figure.js — Three.js-голограмма Джарвиса: женская модель (Michelle, three.js CC-ассеты)
// под голограмм-шейдером в стиле Джои из «Бегущего по лезвию 2049».
// Загружается лениво (dynamic import) — three.js и модель не сидят в основном бандле.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { VideoFigure } from './video.js';

// модель голограммы переключается: window.__holo.useModel('michelle'|'kira'|'xbot'|'2b')
// (localStorage holo-model) — по умолчанию michelle.
// pick: имя узла-персонажа, если модель — сцена с окружением (kira = девушка в спальне)
// rotY: доворот к камере (Sketchfab-экспорты часто стоят спиной)
const MODELS = {
    michelle: { url: '/models/michelle.glb' },
    xbot: { url: '/models/xbot.glb' },
    '2b': { url: '/models/2b.glb', rotY: Math.PI },   // модель владельца: NieR 2B, статичная
    face: { url: '/models/facecap.glb', allClips: true, height: 1.25 }, // говорящая голова: 52 морфа + глаза
    video: { type: 'video' },   // ролики владельца: public/models/video/{idle,listening,thinking,speaking}.webm
};
const MODEL_CFG = MODELS[localStorage.getItem('holo-model')] || MODELS.michelle;
const MODEL_URL = MODEL_CFG.url;
const FIGURE_HEIGHT = 1.72;   // рост модели в сцене, ступни на y=0
const DANCE_TIMESCALE = 0.12; // Samba → медленное грациозное покачивание

const PALETTE = {
    bodyLow: new THREE.Color('#ff6ec7'),   // розовый (тело)
    bodyHigh: new THREE.Color('#ffb3ec'),  // светло-розовый (лёгкие фронтальные поверхности)
    rim: new THREE.Color('#8ff7ea'),       // мятно-циановая кайма
    blue: new THREE.Color('#57a8ff'),      // думанье
};

// ------------------------------------------------------------------
// Голограмм-шейдер поверх скелетной модели
// ------------------------------------------------------------------

const HOLO_VERT = /* glsl */ `
#include <common>
#include <skinning_pars_vertex>
#include <morphtarget_pars_vertex>
varying vec3 vViewNormal;
varying vec3 vWorldPos;
varying vec2 vUv;
void main() {
    #include <beginnormal_vertex>
    #include <morphnormal_vertex>
    #include <skinbase_vertex>
    #include <skinnormal_vertex>
    #include <begin_vertex>
    #include <morphtarget_vertex>
    #include <skinning_vertex>

    vec4 world = modelMatrix * vec4(transformed, 1.0);
    vWorldPos = world.xyz;
    vViewNormal = normalize(normalMatrix * objectNormal);
    vUv = uv;
    gl_Position = projectionMatrix * viewMatrix * world;
}
`;

const HOLO_FRAG = /* glsl */ `
uniform vec3 uColA;     // розовый — тело
uniform vec3 uColB;     // светло-розовый — фронт
uniform vec3 uColRim;   // циановая кайма
uniform vec3 uColC;     // синий — думанье
uniform float uTime;
uniform float uState;
uniform float uAmp;
uniform float uGlitch;
uniform float uAssemble;
uniform float uFade;
uniform vec2 uReveal;      // min/max мировой Y модели
uniform sampler2D uMap;    // собственная текстура модели (если есть)
uniform float uMapMix;     // 0 — чистая голограмма, 1 — цвета модели видны
varying vec3 vViewNormal;
varying vec3 vWorldPos;
varying vec2 vUv;

void main() {
    // «проявление» снизу-вверх: выше кромки фрагменты отбрасываются
    float reveal = mix(uReveal.x, uReveal.y, uAssemble);
    float above = vWorldPos.y - reveal;
    if (above > 0.0) discard;
    float edgeBand = 1.0 - smoothstep(0.0, 0.045, -above); // яркая кромка проявления

    // френель: кайма по контуру, слабое полупрозрачное тело
    float fres = pow(1.0 - abs(vViewNormal.z), 2.2);
    float fill = 0.11 + 0.08 * abs(vViewNormal.z);

    // собственные цвета модели (бэк-текстура): без них у симметричных
    // персонажей перед/зад неотличимы
    vec3 tex = texture2D(uMap, vUv).rgb;
    float texLum = dot(tex, vec3(0.33));

    // сканлайны (циановые волны по телу) и общее мерцание
    float scanWave = sin(vWorldPos.y * 130.0 - uTime * 3.0);
    float scan = 0.75 + 0.25 * scanWave;
    float flick = 0.9 + 0.1 * sin(uTime * 43.0) * sin(uTime * 17.0 + vWorldPos.y * 3.0);

    // глитч: полосы выпадения + сдвиг яркости
    float glitch = 0.0;
    if (uGlitch > 0.001) {
        float band = step(0.75, fract(vWorldPos.y * 7.0 + floor(uTime * 20.0) * 0.31));
        glitch = uGlitch * band;
        if (fract(vWorldPos.y * 3.0 + floor(uTime * 24.0)) > 0.97) discard;
    }

    vec3 col = mix(uColA, uColB, 0.35 + 0.65 * clamp(abs(vViewNormal.z), 0.0, 1.0));
    col = mix(col, uColRim, clamp(fres * 1.15, 0.0, 1.0) * 0.75 + edgeBand * 0.8);
    // цвета модели УМНОЖАЮТСЯ на палитру: белые волосы ярче, чёрное платье
    // глубже — но голограммное свечение не гаснет (аддитивный блендинг)
    col *= mix(vec3(1.0), 0.45 + 0.9 * tex, 0.6 * uMapMix);
    col += uColRim * 0.20 * max(0.0, scanWave);   // сканлайны подкрашивают цианом
    if (uState > 1.5 && uState < 2.5) col = mix(col, uColC, 0.5);

    float alpha = (fill + fres * 1.25 + edgeBand * 1.4) * scan * flick * uFade;
    // тёмные участки текстуры чуть прозрачнее, светлые — плотнее
    alpha *= mix(1.0, 0.78 + 0.35 * texLum, uMapMix);
    alpha *= (1.0 - glitch * 0.55);
    alpha *= 0.72 + 0.28 * uAmp;

    // слушание: бегущая снизу волна в такт микрофону
    if (uState > 0.5 && uState < 1.5) {
        float wave = sin(vWorldPos.y * 22.0 - uTime * 5.0);
        alpha += 0.12 * max(0.0, wave) * (0.3 + uAmp);
        col = mix(col, uColA, 0.25);
    }
    // говорение: пульс каймы в такт речи
    if (uState > 2.5) {
        col += uColRim * (0.10 + 0.16 * uAmp);
    }

    gl_FragColor = vec4(col * (1.0 + edgeBand * 1.6 + fres * 0.6 + uGlitch), clamp(alpha, 0.0, 1.0) * 0.95);
}
`;

const CONE_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const CONE_FRAG = /* glsl */ `
uniform vec3 uColA;
uniform vec3 uColB;
uniform float uTime;
uniform float uFade;
varying vec2 vUv;
void main() {
    float base = (1.0 - vUv.y) * 0.075;
    float rings = 0.028 * (0.5 + 0.5 * sin(vUv.y * 26.0 - uTime * 2.2));
    float edge = sin(vUv.x * 3.14159);
    vec3 col = mix(uColA, uColB, vUv.y);
    gl_FragColor = vec4(col, (base + rings) * edge * uFade);
}
`;

// ------------------------------------------------------------------
// Мягкое свечение (fake bloom) — canvas-текстура radial gradient
// ------------------------------------------------------------------

function makeGlowTexture(hex = '#7ff5e8') {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, hex);
    g.addColorStop(0.25, hex + 'aa');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

// ------------------------------------------------------------------
// Пылинки в конусе
// ------------------------------------------------------------------

function buildDust() {
    const N = 320;
    const pos = new Float32Array(N * 3);
    const vel = new Float32Array(N);
    for (let i = 0; i < N; i++) {
        const y = 0.05 + Math.random() * 1.75;
        const rr = 0.08 + (y / 1.8) * 0.5 * Math.sqrt(Math.random());
        const a = Math.random() * Math.PI * 2;
        pos[i * 3] = Math.cos(a) * rr;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = Math.sin(a) * rr;
        vel[i] = 0.03 + Math.random() * 0.06;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const m = new THREE.PointsMaterial({
        size: 0.03,
        map: makeGlowTexture('#9ff2ff'),
        transparent: true,
        opacity: 0.35,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(g, m);
    return { points, vel };
}

// ------------------------------------------------------------------
// Твин-хелпер (без GSAP). rAF замерзает в перекрытых окнах — интервал.
// ------------------------------------------------------------------

function tween(from, to, ms, onUpdate, ease = (t) => 1 - Math.pow(1 - t, 3)) {
    return new Promise((resolve) => {
        const t0 = performance.now();
        const iv = setInterval(() => {
            const k = Math.min(1, (performance.now() - t0) / ms);
            onUpdate(from + (to - from) * ease(k));
            if (k >= 1) {
                clearInterval(iv);
                resolve();
            }
        }, 16);
    });
}

// ------------------------------------------------------------------
// Класс сцены
// ------------------------------------------------------------------

const STATE_IDS = { idle: 0, listening: 1, thinking: 2, speaking: 3 };

// фабрика: видеоголограмма или 3D-модель — единый API для hologram.js
export function createFigure(container) {
    return MODEL_CFG.type === 'video'
        ? new VideoFigure(container)
        : new HoloFigure(container);
}

export class HoloFigure {
    static _white = null;

    // 1×1 белая текстура-заглушка для самплера без карты
    static whiteTex() {
        if (!HoloFigure._white) {
            const t = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
            t.needsUpdate = true;
            HoloFigure._white = t;
        }
        return HoloFigure._white;
    }

    constructor(container) {
        this.container = container;
        this.state = 'idle';
        this.visible = false;
        this._time = 0;
        this._raf = null;
        this._wdg = null;
        this._lastT = 0;
        this.mixer = null;

        this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        this.renderer.setClearColor(0x000000, 0);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
        this.renderer.domElement.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;';
        container.appendChild(this.renderer.domElement);

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(37, 1, 0.1, 50);
        this.camera.position.set(0, 1.52, 5.15);
        this.camera.lookAt(0, 0.98, 0);

        this.group = new THREE.Group();
        this.scene.add(this.group);

        // --- модель под шейдером
        this.uni = {
            uTime: { value: 0 },
            uState: { value: 0 },
            uAmp: { value: 0 },
            uGlitch: { value: 0 },
            uAssemble: { value: 0 },
            uFade: { value: 1 },
            uReveal: { value: new THREE.Vector2(0, FIGURE_HEIGHT) },
            uColA: { value: PALETTE.bodyLow },
            uColB: { value: PALETTE.bodyHigh },
            uColRim: { value: PALETTE.rim },
            uColC: { value: PALETTE.blue },
            uMap: { value: HoloFigure.whiteTex() },
            uMapMix: { value: 0 },
        };
        this.holoMat = new THREE.ShaderMaterial({
            uniforms: this.uni,
            vertexShader: HOLO_VERT,
            fragmentShader: HOLO_FRAG,
            transparent: true,
            depthWrite: false,
            side: THREE.FrontSide, // задние грани не светят поверх — без «гранёности»
            blending: THREE.AdditiveBlending,
        });
        this._ready = this._loadModel();

        // --- конус света от пьедестала
        this.coneUni = {
            uColA: { value: PALETTE.bodyLow },
            uColB: { value: PALETTE.rim },
            uTime: { value: 0 },
            uFade: { value: 1 },
        };
        const coneMat = new THREE.ShaderMaterial({
            uniforms: this.coneUni,
            vertexShader: CONE_VERT,
            fragmentShader: CONE_FRAG,
            transparent: true,
            depthWrite: false,
            side: THREE.DoubleSide,
            blending: THREE.AdditiveBlending,
        });
        this.cone = new THREE.Mesh(
            new THREE.CylinderGeometry(0.1, 0.62, 1.85, 48, 1, true),
            coneMat
        );
        this.cone.position.y = 0.925;
        this.group.add(this.cone);

        // --- пьедестал: свечение, эмиттер, расходящиеся кольца
        this.glow = new THREE.Sprite(new THREE.SpriteMaterial({
            map: makeGlowTexture('#f58fd4'),
            transparent: true,
            opacity: 0.5,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        }));
        this.glow.scale.set(1.7, 0.85, 1);
        this.glow.position.y = 0.05;
        this.group.add(this.glow);

        this.emitter = new THREE.Sprite(new THREE.SpriteMaterial({
            map: makeGlowTexture('#ffd9f2'),
            transparent: true,
            opacity: 0.95,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        }));
        this.emitter.scale.set(0.3, 0.16, 1);
        this.emitter.position.y = 0.02;
        this.group.add(this.emitter);

        this.rings = [];
        for (let i = 0; i < 2; i++) {
            const ring = new THREE.Mesh(
                new THREE.RingGeometry(0.96, 1.0, 64),
                new THREE.MeshBasicMaterial({
                    color: PALETTE.bodyLow,
                    transparent: true,
                    opacity: 0,
                    depthWrite: false,
                    side: THREE.DoubleSide,
                    blending: THREE.AdditiveBlending,
                })
            );
            ring.rotation.x = -Math.PI / 2;
            ring.position.y = 0.01 + i * 0.005;
            this.group.add(ring);
            this.rings.push(ring);
        }

        // --- пылинки
        this.dust = buildDust();
        this.group.add(this.dust.points);

        this._onResize = this.resize.bind(this);
        window.addEventListener('resize', this._onResize);
        this.resize();
    }

    async _loadModel() {
        const loader = new GLTFLoader();
        const draco = new DRACOLoader();          // сжатые меши (kira и др.)
        draco.setDecoderPath('/models/draco/');
        loader.setDRACOLoader(draco);
        const ktx2 = new KTX2Loader()             // facecap и др. с KTX2-текстурами
            .setTranscoderPath('/models/basis/')
            .detectSupport(this.renderer);
        loader.setKTX2Loader(ktx2);
        loader.setMeshoptDecoder(MeshoptDecoder);  // + EXT_meshopt_compression
        const gltf = await loader.loadAsync(MODEL_URL);
        let root = gltf.scene;
        // сцена-с-окружением: оставляем только узел-персонажа (скелет внутри него)
        if (MODEL_CFG.pick) {
            const charNode = root.getObjectByName(MODEL_CFG.pick);
            if (charNode) {
                root = new THREE.Group();
                root.add(charNode);
            }
        }
        const model = root;

        // рост → (для бюста свой), ступни на y=0, центрирование по x/z
        const box = new THREE.Box3().setFromObject(model);
        const size = new THREE.Vector3(); box.getSize(size);
        const scale = (MODEL_CFG.height || FIGURE_HEIGHT) / Math.max(0.01, size.y);
        model.scale.setScalar(scale);
        model.updateMatrixWorld(true);

        const box2 = new THREE.Box3().setFromObject(model);
        const center = new THREE.Vector3(); box2.getCenter(center);
        model.position.x -= center.x;
        model.position.z -= center.z;
        model.position.y -= box2.min.y;
        model.updateMatrixWorld(true);

        const box3 = new THREE.Box3().setFromObject(model);
        this.uni.uReveal.value.set(box3.min.y - 0.02, box3.max.y + 0.06);

        // доворот к камере (базовый поворот для процедурного покачивания)
        this._modelBaseRotY = MODEL_CFG.rotY || 0;
        model.rotation.y = this._modelBaseRotY;

        // голограмм-материал на все меши; у мешей со своей текстурой
        // подмешиваем цвета модели (иначе перед/зад неразличимы).
        // NB: ShaderMaterial.clone() глубоко копирует юниформы — твины и
        // состояния должны жить в ОБЩИХ объектах, поэтому подменяем клону
        // юниформы ссылками на базовые (кроме текстурных)
        model.traverse((o) => {
            if (o.isMesh || o.isSkinnedMesh) {
                const tex = o.material?.map || null;
                if (tex) tex.colorSpace = THREE.SRGBColorSpace;
                const mat = this.holoMat.clone();
                mat.uniforms = Object.assign({}, this.uni, {
                    uMap: { value: tex || HoloFigure.whiteTex() },
                    uMapMix: { value: tex ? 1 : 0 },
                });
                o.material = mat;
                o.frustumCulled = false;
            }
        });
        this.model = model;
        this.group.add(model);

        // анимация: allClips (говорящая голова) — играем всё сразу
        // (мимика + глаза + голова); иначе предпочитаем idle/танец,
        // а без клипов — процедурное покачивание
        const anims = gltf.animations || [];
        if (MODEL_CFG.allClips && anims.length) {
            this.mixer = new THREE.AnimationMixer(model);
            anims.forEach((c) => {
                const a = this.mixer.clipAction(c);
                a.timeScale = 1;
                a.play();
            });
        } else {
            const clip = anims.find((a) => /idle/i.test(a.name))
                || anims.find((a) => /samba|dance/i.test(a.name))
                || anims[0];
            if (clip) {
                this.mixer = new THREE.AnimationMixer(model);
                const action = this.mixer.clipAction(clip);
                // idle сам медленный — берём ×0.4; танцы замираем до покачивания ×0.12
                action.timeScale = /idle/i.test(clip.name) ? 0.4
                    : /samba|dance/i.test(clip.name) ? DANCE_TIMESCALE
                    : 0.35;
                action.play();
            } else {
                this._sway = true;
                this._modelBaseY = model.position.y;
            }
        }
    }

    resize() {
        const w = this.container.clientWidth || window.innerWidth;
        const h = this.container.clientHeight || window.innerHeight;
        this.renderer.setSize(w, h);
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        // на широком экране фигура в правой трети, на узком — по центру
        this.group.position.x = w > 980 ? 1.35 : 0;
    }

    setState(name) {
        if (!(name in STATE_IDS)) return;
        this.state = name;
        tween(this.uni.uState.value, STATE_IDS[name], 450, (x) => (this.uni.uState.value = x));
        // слушание — пьедестал розовеет
        const col = name === 'listening' ? PALETTE.bodyLow : PALETTE.rim;
        this.rings.forEach((r) => r.material.color.lerp(col, 1));
    }

    setAmp(v) {
        this.uni.uAmp.value += (Math.max(0, Math.min(1, v)) - this.uni.uAmp.value) * 0.35;
    }

    glitch(strength = 1, ms = 200) {
        const u = this.uni.uGlitch;
        tween(strength, 0, ms, (x) => (u.value = x)).then(() => (u.value = 0));
    }

    async show() {
        await this._ready;
        this.visible = true;
        this.renderer.domElement.style.display = 'block';
        this.glitch(0.8, 400);
        // проявление снизу-вверх + разгорание конуса
        await tween(0, 1, 1700, (x) => {
            this.uni.uAssemble.value = x;
            this.uni.uFade.value = 0.25 + x * 0.75;
            this.coneUni.uFade.value = x;
        });
        this.glitch(0.5, 220);
    }

    async hide() {
        await this._ready;
        this.glitch(1, 320);
        await tween(1, 0, 750, (x) => {
            this.uni.uAssemble.value = x;
            this.uni.uFade.value = 0.25 + x * 0.75;
            this.coneUni.uFade.value = x;
        }, (t) => t * t);
        this.visible = false;
        this.stop();
        this.renderer.domElement.style.display = 'none';
    }

    start() {
        if (this._raf) return;
        this._lastT = performance.now();
        // гибридный драйвер: rAF + интервальный сторож — рендер живёт
        // даже когда браузер замораживает rAF в перекрытом окне
        const loop = (t) => {
            this._raf = requestAnimationFrame(loop);
            this._maybeTick(t);
        };
        this._raf = requestAnimationFrame(loop);
        this._wdg = setInterval(() => this._maybeTick(performance.now()), 40);
    }

    _maybeTick(t) {
        const dt = (t - this._lastT) / 1000;
        if (dt < 0.015) return;
        this._lastT = t;
        if (!this.visible || document.hidden) return;
        this._tick(Math.min(0.05, dt));
    }

    stop() {
        if (this._raf) cancelAnimationFrame(this._raf);
        this._raf = null;
        if (this._wdg) clearInterval(this._wdg);
        this._wdg = null;
    }

    _tick(dt) {
        this._time += dt;
        const t = this._time;
        this.uni.uTime.value = t;
        this.coneUni.uTime.value = t;

        if (this.mixer) this.mixer.update(dt * (this.state === 'thinking' ? 0.4 : 1));

        // статичные модели: процедурная жизнь — дыхание и мягкое покачивание
        if (this._sway && this.model) {
            this.model.position.y = this._modelBaseY + Math.sin(t * 0.9) * 0.008;
            this.model.rotation.y = (this._modelBaseRotY || 0) + Math.sin(t * 0.23) * 0.09;
            this.model.rotation.z = Math.sin(t * 0.5) * 0.015;
        }

        // лёгкий параллакс камеры — сцена живая
        this.camera.position.x = Math.sin(t * 0.21) * 0.05;
        this.camera.position.y = 1.52 + Math.sin(t * 0.17) * 0.02;
        this.camera.lookAt(this.group.position.x, 0.98, 0);

        // кольца пьедестала расходятся и тают
        this.rings.forEach((ring, i) => {
            const phase = (t * 0.4 + i * 0.5) % 1;
            const s = 0.35 + phase * 1.6;
            ring.scale.set(s, s, 1);
            ring.material.opacity = (1 - phase) * 0.4 * this.uni.uAssemble.value;
        });

        // пульс эмиттера
        const pulse = 0.75 + 0.25 * Math.sin(t * 2.4) + this.uni.uAmp.value * 0.6;
        this.emitter.material.opacity = Math.min(1, 0.6 * pulse);
        this.glow.material.opacity = (0.35 + this.uni.uAmp.value * 0.4) * this.uni.uAssemble.value;

        // пылинки всплывают
        const dp = this.dust.points.geometry.attributes.position;
        const vel = this.dust.vel;
        for (let i = 0; i < vel.length; i++) {
            let y = dp.getY(i) + vel[i] * dt;
            if (y > 1.8) y = 0.05;
            dp.setY(i, y);
        }
        dp.needsUpdate = true;

        this.renderer.render(this.scene, this.camera);
    }

    dispose() {
        this.stop();
        window.removeEventListener('resize', this._onResize);
        this.scene.traverse((o) => {
            if (o.geometry) o.geometry.dispose();
            if (o.material) {
                if (o.material.map) o.material.map.dispose();
                o.material.dispose();
            }
        });
        this.renderer.dispose();
        this.renderer.domElement.remove();
    }
}
