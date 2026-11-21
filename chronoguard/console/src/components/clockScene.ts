import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export type ClockPose = { yaw: number; pitch: number; scroll: number; moving: boolean; now: () => number };
const circle = Math.PI * 2;

function dialTexture() {
  const face = document.createElement('canvas');
  face.width = face.height = 1024;
  const ctx = face.getContext('2d')!;
  ctx.translate(512, 512);
  const enamel = ctx.createLinearGradient(-430, -500, 440, 450);
  enamel.addColorStop(0, '#407365');
  enamel.addColorStop(0.48, '#1c5147');
  enamel.addColorStop(1, '#103c36');
  ctx.fillStyle = enamel;
  ctx.fillRect(-512, -512, 1024, 1024);
  for (let radius = 8; radius < 505; radius += 3) {
    ctx.beginPath(); ctx.arc(0, 0, radius, 0, circle);
    ctx.strokeStyle = radius % 2 ? 'rgba(226,239,208,.06)' : 'rgba(5,37,30,.10)';
    ctx.lineWidth = 1; ctx.stroke();
  }
  for (let tick = 0; tick < 120; tick++) {
    ctx.save(); ctx.rotate(tick * circle / 120);
    const major = tick % 10 === 0;
    ctx.fillStyle = major ? '#efe5c4' : '#a5bcb0';
    const width = major ? 7 : tick % 2 === 0 ? 3 : 1;
    ctx.fillRect(-width / 2, -466, width, major ? 33 : tick % 2 === 0 ? 15 : 8);
    ctx.restore();
  }
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = '#f2e7c9'; ctx.font = '64px Georgia, serif';
  for (const hour of [12, 3, 6, 9]) {
    const angle = hour * circle / 12;
    ctx.fillText(String(hour), Math.sin(angle) * 375, -Math.cos(angle) * 375 + 3);
  }
  ctx.lineWidth = 1.6; ctx.strokeStyle = '#a9b79b';
  for (const radius of [481, 425, 302]) {
    ctx.beginPath(); ctx.arc(0, 0, radius, 0, circle); ctx.stroke();
  }
  ctx.fillStyle = '#e9e1be'; ctx.font = '27px Georgia, serif'; ctx.fillText('ChronoGuard', 0, -145);
  ctx.font = '20px sans-serif'; ctx.fillText('UTC', 0, 175);
  const texture = new THREE.CanvasTexture(face);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function mountClock(canvas: HTMLCanvasElement, pose: ClockPose) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.6));
  renderer.setClearColor(0, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.18;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
  const room = new RoomEnvironment();
  const generator = new THREE.PMREMGenerator(renderer);
  const lightMap = generator.fromScene(room, 0.06);
  room.dispose(); generator.dispose();
  scene.environment = lightMap.texture;
  scene.environmentIntensity = 0.92;
  const key = new THREE.DirectionalLight(0xfff4dd, 2.2);
  key.position.set(-3, 5, 6);
  scene.add(key, new THREE.HemisphereLight(0xf5fff6, 0x879989, 1.2));
  const instrument = new THREE.Group();
  instrument.rotation.order = 'YXZ';
  scene.add(instrument);
  const brass = new THREE.MeshStandardMaterial({ color: 0xb69458, metalness: 0.88, roughness: 0.27 });
  const champagne = new THREE.MeshStandardMaterial({ color: 0xd8bb82, metalness: 0.79, roughness: 0.22 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x173b31, metalness: 0.64, roughness: 0.32 });
  const ivory = new THREE.MeshStandardMaterial({ color: 0xffe9ba, metalness: 0.34, roughness: 0.30 });
  const vermilion = new THREE.MeshStandardMaterial({ color: 0xd36337, metalness: 0.32, roughness: 0.30 });
  function mount(geometry: THREE.BufferGeometry, material: THREE.Material, group = instrument) {
    const mesh = new THREE.Mesh(geometry, material);
    group.add(mesh);
    return mesh;
  }
  function rim(radius: number, thickness: number, z: number, material: THREE.Material, group = instrument) {
    const mesh = mount(new THREE.TorusGeometry(radius, thickness, 14, 128), material, group);
    mesh.position.z = z;
    return mesh;
  }
  function disc(radius: number, depth: number, z: number, material: THREE.Material) {
    const mesh = mount(new THREE.CylinderGeometry(radius, radius, depth, 128), material);
    mesh.rotation.x = Math.PI / 2; mesh.position.z = z;
    return mesh;
  }
  const suspension = new THREE.Group();
  suspension.rotation.set(-0.44, 0.24, -0.18); suspension.position.z = -0.19;
  instrument.add(suspension);
  rim(1.98, 0.055, 0, champagne, suspension);
  rim(1.98, 0.025, -0.075, brass, suspension);
  for (const side of [-1, 1]) {
    const axle = mount(new THREE.CylinderGeometry(0.096, 0.096, 0.42, 28), brass, suspension);
    axle.rotation.z = Math.PI / 2; axle.position.x = side * 1.83;
  }
  disc(1.66, 0.40, -0.04, brass);
  disc(1.69, 0.22, -0.05, dark);
  const ribs = new THREE.InstancedMesh(new THREE.BoxGeometry(0.016, 0.039, 0.22), brass, 180);
  const mark = new THREE.Object3D();
  for (let i = 0; i < ribs.count; i++) {
    const a = i * circle / ribs.count;
    mark.position.set(1.68 * Math.sin(a), 1.68 * Math.cos(a), -0.045);
    mark.rotation.z = -a; mark.updateMatrix(); ribs.setMatrixAt(i, mark.matrix);
  }
  instrument.add(ribs);
  rim(1.655, 0.055, -0.235, champagne);
  rim(1.66, 0.055, 0.11, brass);
  rim(1.61, 0.085, 0.19, champagne);
  rim(1.52, 0.027, 0.221, dark);
  const texture = dialTexture();
  const dial = mount(new THREE.CircleGeometry(1.54, 144), new THREE.MeshBasicMaterial({ map: texture, toneMapped: false }));
  dial.position.z = 0.204;
  rim(1.505, 0.012, 0.23, champagne);
  function hand(length: number, width: number, tail: number, z: number, material: THREE.Material) {
    const outline = new THREE.Shape();
    outline.moveTo(0, length); outline.lineTo(width, length * 0.34);
    outline.lineTo(width * 0.50, -tail); outline.lineTo(-width * 0.50, -tail);
    outline.lineTo(-width, length * 0.34); outline.closePath();
    const mesh = mount(new THREE.ExtrudeGeometry(outline, { depth: 0.012, bevelEnabled: false }), material);
    mesh.position.z = z;
    return mesh;
  }
  const hour = hand(0.88, 0.060, 0.18, 0.25, champagne);
  const minute = hand(1.22, 0.043, 0.19, 0.28, ivory);
  const second = hand(1.33, 0.018, 0.34, 0.312, vermilion);
  disc(0.078, 0.040, 0.34, champagne);
  disc(0.031, 0.018, 0.365, dark);
  const parent = canvas.parentElement!;
  let visible = true, frame = 0, previous = -1000, activeTime = 0, lastDraw = '';
  let yaw = -0.28, pitch = 0.42;
  function render(now: number) {
    frame = 0;
    if (!visible || document.hidden) return;
    if (now - previous >= 33) {
      if (pose.moving) activeTime += Math.min(now - previous, 45) / 1000;
      previous = now;
      const sweep = pose.moving ? 0.14 * Math.sin(activeTime * 0.32) : 0;
      const targetYaw = -0.28 + pose.yaw + sweep + pose.scroll * 0.78;
      const targetPitch = 0.42 + pose.pitch + pose.scroll * 0.20;
      yaw += (targetYaw - yaw) * (pose.moving ? 0.16 : 1);
      pitch += (targetPitch - pitch) * (pose.moving ? 0.16 : 1);
      const date = new Date(pose.now()), seconds = date.getUTCSeconds();
      const signature = [yaw.toFixed(4), pitch.toFixed(4), date.toISOString().slice(0, 19)].join('/');
      if (signature !== lastDraw) {
        instrument.rotation.set(pitch, yaw, -0.34 + pose.scroll * 0.12, 'YXZ');
        second.rotation.z = -seconds * circle / 60;
        minute.rotation.z = -(date.getUTCMinutes() + seconds / 60) * circle / 60;
        hour.rotation.z = -(date.getUTCHours() + date.getUTCMinutes() / 60) * circle / 12;
        renderer.render(scene, camera);
        lastDraw = signature;
      }
    }
    if (pose.moving) frame = requestAnimationFrame(render);
  }
  function wake() { if (!frame && visible && !document.hidden) frame = requestAnimationFrame(render); }
  function resize() {
    const w = Math.max(parent.clientWidth, 1), h = Math.max(parent.clientHeight, 1);
    camera.aspect = w / h;
    camera.position.z = 8.40 / Math.min(1, camera.aspect);
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false); lastDraw = ''; previous = -1000; wake();
  }
  const size = new ResizeObserver(resize); size.observe(parent); resize();
  const view = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; wake(); });
  view.observe(canvas);
  document.addEventListener('visibilitychange', wake);
  const tick = window.setInterval(wake, 1000);
  return {
    wake,
    dispose() {
      cancelAnimationFrame(frame); clearInterval(tick); size.disconnect(); view.disconnect();
      document.removeEventListener('visibilitychange', wake);
      const materials = new Set<THREE.Material>();
      scene.traverse(node => { if (node instanceof THREE.Mesh) {
        node.geometry.dispose(); for (const mat of Array.isArray(node.material) ? node.material : [node.material]) materials.add(mat);
      }});
      materials.forEach(mat => mat.dispose()); texture.dispose(); lightMap.dispose(); renderer.dispose(); renderer.forceContextLoss();
    },
  };
}
