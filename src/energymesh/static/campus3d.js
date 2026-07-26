import * as THREE from "/static/vendor/three.module.min.js";

const white = new THREE.MeshStandardMaterial({ color: 0xf4f6f7, roughness: 0.72 });
const side = new THREE.MeshStandardMaterial({ color: 0xd9e0e4, roughness: 0.8 });
const dark = new THREE.MeshStandardMaterial({ color: 0x91a0aa, roughness: 0.6 });
const glass = new THREE.MeshStandardMaterial({ color: 0x92afc0, roughness: 0.3, metalness: 0.15 });
const solar = new THREE.MeshStandardMaterial({ color: 0x365a72, roughness: 0.45, metalness: 0.1 });
const energyGreen = new THREE.MeshStandardMaterial({
  color: 0x69e66e,
  emissive: 0x1f8f48,
  emissiveIntensity: 0.45,
});

function box(group, size, position, material = white) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function addWindows(group, count, origin, spacing) {
  for (let index = 0; index < count; index += 1) {
    box(group, [.08, .34, .42], [origin[0], origin[1], origin[2] + index * spacing], glass);
  }
}

function factory(scene) {
  const group = new THREE.Group();
  box(group, [4.8, 1.25, 3.2], [-4.4, .64, -1.9]);
  box(group, [2.2, .8, 1.2], [-6.2, .42, .25], side);
  for (let index = 0; index < 3; index += 1) {
    const stack = new THREE.Mesh(new THREE.CylinderGeometry(.22, .26, 1.7, 18), side);
    stack.position.set(-5.6 + index * 1.1, 1.8, -2.2);
    stack.castShadow = true;
    group.add(stack);
  }
  addWindows(group, 5, [-1.98, .62, -3.0], .55);
  scene.add(group);
}

function solarField(scene) {
  const group = new THREE.Group();
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 5; column += 1) {
      const panel = box(group, [.92, .08, .62], [-1.9 + column, .48, -5.4 + row * .8], solar);
      panel.rotation.x = -.22;
    }
  }
  scene.add(group);
}

function battery(scene) {
  const group = new THREE.Group();
  for (let index = 0; index < 4; index += 1) {
    box(group, [.8, 2.05, 1.05], [5.3 + index * .92, 1.03, -2.7], index % 2 ? side : white);
    box(group, [.55, .08, .45], [5.3 + index * .92, 1.38, -2.15], dark);
  }
  scene.add(group);
}

function computeCenter(scene) {
  const group = new THREE.Group();
  box(group, [4.2, 1.2, 2.7], [5.1, .62, 3.4]);
  box(group, [3.2, .26, 1.8], [5.1, 1.34, 3.4], side);
  for (let index = 0; index < 5; index += 1) {
    box(group, [.08, .45, .34], [2.97, .66, 2.45 + index * .45], glass);
  }
  for (let index = 0; index < 3; index += 1) {
    const fan = new THREE.Mesh(new THREE.CylinderGeometry(.32, .32, .18, 20), dark);
    fan.position.set(4.2 + index * .9, 1.58, 3.4);
    group.add(fan);
  }
  scene.add(group);
}

function chargers(scene) {
  const group = new THREE.Group();
  for (let index = 0; index < 3; index += 1) {
    box(group, [.35, 1.25, .48], [-.9 + index * 1.05, .63, 5.1], white);
    box(group, [.23, .28, .04], [-.9 + index * 1.05, .82, 4.85], glass);
  }
  box(group, [2.7, .35, 1.15], [1.1, .2, 5.7], side);
  scene.add(group);
}

function grid(scene) {
  const group = new THREE.Group();
  const towerMaterial = new THREE.LineBasicMaterial({ color: 0x98a6af });
  const points = [
    [-7.1, 0, 4.2], [-7.1, 3.8, 4.2], [-8.05, .1, 4.2], [-7.1, 3.8, 4.2],
    [-6.15, .1, 4.2], [-7.1, 3.8, 4.2], [-7.9, 1.4, 4.2], [-6.3, 1.4, 4.2],
    [-7.65, 2.35, 4.2], [-6.55, 2.35, 4.2],
  ].map((point) => new THREE.Vector3(...point));
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  group.add(new THREE.LineSegments(geometry, towerMaterial));
  for (let index = 0; index < 3; index += 1) {
    const wirePoints = [
      new THREE.Vector3(-7.7 + index * .6, 2.35, 4.2),
      new THREE.Vector3(-4.8 + index * .4, 1.5, 1.2),
    ];
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(wirePoints), towerMaterial));
  }
  scene.add(group);
}

function energyPath(scene, from, to, particles) {
  const mid = new THREE.Vector3((from[0] + to[0]) / 2, .12, (from[2] + to[2]) / 2);
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(...from),
    new THREE.Vector3(mid.x, .12, mid.z),
    new THREE.Vector3(...to),
  ]);
  const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 28, .035, 7, false), energyGreen);
  scene.add(tube);
  for (let index = 0; index < 3; index += 1) {
    const particle = new THREE.Mesh(new THREE.SphereGeometry(.11, 12, 12), energyGreen);
    particle.userData = { curve, offset: index / 3 + particles.length * .11 };
    particles.push(particle);
    scene.add(particle);
  }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function createCampus3D(canvas, onLabels) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xf9fafa);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xf9fafa, 24, 38);
  const camera = new THREE.OrthographicCamera(-10, 10, 6.2, -6.2, .1, 100);
  let azimuth = -.75;
  let elevation = .72;
  let zoom = 1;
  let dragging = false;
  let pointer = [0, 0];

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(24, 18),
    new THREE.MeshStandardMaterial({ color: 0xf1f4f4, roughness: 1 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const gridHelper = new THREE.GridHelper(24, 24, 0xdce3e6, 0xe7ecee);
  gridHelper.position.y = .015;
  scene.add(gridHelper);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xbfcbd1, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 3.2);
  sun.position.set(-8, 14, 9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -14;
  sun.shadow.camera.right = 14;
  sun.shadow.camera.top = 12;
  sun.shadow.camera.bottom = -12;
  scene.add(sun);

  factory(scene);
  solarField(scene);
  battery(scene);
  computeCenter(scene);
  chargers(scene);
  grid(scene);

  const hub = new THREE.Mesh(new THREE.CylinderGeometry(.34, .34, .12, 24), energyGreen);
  hub.position.set(0, .08, 0);
  scene.add(hub);
  const particles = [];
  energyPath(scene, [-5.4, .12, 2.3], [0, .12, 0], particles);
  energyPath(scene, [-.2, .12, -4.1], [0, .12, 0], particles);
  energyPath(scene, [5.4, .12, -1.5], [0, .12, 0], particles);
  energyPath(scene, [0, .12, 0], [4.7, .12, 2.1], particles);
  energyPath(scene, [0, .12, 0], [.3, .12, 4.5], particles);
  energyPath(scene, [0, .12, 0], [-3.5, .12, -1.2], particles);
  const labelAnchors = {
    factory: new THREE.Vector3(-4.4, 1.55, -1.9),
    solar: new THREE.Vector3(.1, .82, -4.55),
    storage: new THREE.Vector3(6.65, 2.35, -2.7),
    grid: new THREE.Vector3(-7.1, 3.95, 4.2),
    charge: new THREE.Vector3(.15, .95, 5.1),
    compute: new THREE.Vector3(5.1, 1.75, 3.4),
  };

  function positionCamera() {
    const radius = 20;
    camera.position.set(
      Math.sin(azimuth) * Math.cos(elevation) * radius,
      Math.sin(elevation) * radius,
      Math.cos(azimuth) * Math.cos(elevation) * radius,
    );
    camera.zoom = zoom;
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }

  function resize() {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false);
    const aspect = width / height;
    camera.left = -7.4 * aspect;
    camera.right = 7.4 * aspect;
    camera.top = 7.4;
    camera.bottom = -7.4;
    camera.updateProjectionMatrix();
  }

  function updateLabels() {
    if (!onLabels) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const labels = {};
    Object.entries(labelAnchors).forEach(([key, anchor]) => {
      const projected = anchor.clone().project(camera);
      const x = (projected.x * .5 + .5) * width;
      const y = (-projected.y * .5 + .5) * height;
      labels[key] = {
        x: clamp(x, 48, width - 48),
        y: clamp(y, 34, height - 22),
        visible: projected.z > -1 && projected.z < 1,
      };
    });
    onLabels(labels);
  }

  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    pointer = [event.clientX, event.clientY];
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    azimuth -= (event.clientX - pointer[0]) * .006;
    elevation = Math.max(.35, Math.min(1.15, elevation + (event.clientY - pointer[1]) * .004));
    pointer = [event.clientX, event.clientY];
    positionCamera();
  });
  canvas.addEventListener("pointerup", () => { dragging = false; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom = Math.max(.75, Math.min(1.55, zoom - event.deltaY * .0008));
    positionCamera();
  }, { passive: false });

  let frame = 0;
  function render(time) {
    particles.forEach((particle) => {
      const progress = (time * .00009 + particle.userData.offset) % 1;
      particle.position.copy(particle.userData.curve.getPointAt(progress));
    });
    updateLabels();
    renderer.render(scene, camera);
    frame = requestAnimationFrame(render);
  }

  positionCamera();
  resize();
  render(0);
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);

  return {
    reset() {
      azimuth = -.75;
      elevation = .72;
      zoom = 1;
      positionCamera();
    },
    resize,
    destroy() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.dispose();
    },
  };
}
