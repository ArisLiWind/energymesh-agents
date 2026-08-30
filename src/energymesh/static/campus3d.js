import * as THREE from "/static/vendor/three.module.min.js";

const GRID_STEP = 2;
const GRID_LIMIT = 22;
const HEX_R = 2.1;
const HEX_H = 0.06;

const MODULE_TYPES = {
  factory: { title: "园区用电", metric: "0.00 kW", note: "所有设备总需求", category: "用电端" },
  solar: { title: "自有发电", metric: "0.00 kW", note: "PV 等自发电汇总", category: "发电端" },
  storage: { title: "储能", metric: "SOC 55%", note: "待命 0.00 kW", category: "储能端" },
  grid: { title: "电网购电", metric: "0.00 kW", note: "缺口由外部电网补足", category: "外部输入" },
  charge: { title: "充电负载", metric: "2 MW", note: "日用电量 8 MWh", category: "用电端" },
  compute: { title: "数据负载", metric: "5 MW", note: "日用电量 28 MWh", category: "用电端" },
  datacenter: { title: "数据中心", metric: "6 MW", note: "新增用电端", category: "用电端" },
  generation: { title: "发电机", metric: "20 MW", note: "日发电量 58 MWh", category: "发电端" },
};

const PALETTE = {
  hexWhite: 0xffffff,
  hexGray: 0x999999,
  grass: 0x58c48f,
  treeDark: 0x2d9d6b,
  treeLight: 0x6bd4a0,
  bush: 0x7ec97f,
  buildingWhite: 0xf8fbfd,
  buildingSide: 0xd4e3ed,
  buildingDark: 0x8aa8bd,
  glass: 0x7fd3e0,
  solar: 0x2a6b8a,
  pipe: 0x4ecdc4,
  selected: 0x9ff3e5,
};

const materials = {
  hexWhite: new THREE.MeshStandardMaterial({ color: PALETTE.hexWhite, roughness: 0.35 }),
  hexLight: new THREE.MeshStandardMaterial({ color: PALETTE.hexLight, roughness: 0.35 }),
  hexPale: new THREE.MeshStandardMaterial({ color: PALETTE.hexPale, roughness: 0.35 }),
  grass: new THREE.MeshStandardMaterial({ color: PALETTE.grass, roughness: 1 }),
  tree: new THREE.MeshStandardMaterial({ color: PALETTE.treeDark, roughness: 0.8 }),
  treeLight: new THREE.MeshStandardMaterial({ color: PALETTE.treeLight, roughness: 0.7 }),
  bush: new THREE.MeshStandardMaterial({ color: PALETTE.bush, roughness: 0.9 }),
  white: new THREE.MeshStandardMaterial({ color: PALETTE.buildingWhite, roughness: 0.6 }),
  side: new THREE.MeshStandardMaterial({ color: PALETTE.buildingSide, roughness: 0.7 }),
  dark: new THREE.MeshStandardMaterial({ color: PALETTE.buildingDark, roughness: 0.6 }),
  glass: new THREE.MeshStandardMaterial({ color: PALETTE.glass, roughness: 0.2, metalness: 0.1 }),
  solar: new THREE.MeshStandardMaterial({ color: PALETTE.solar, roughness: 0.35 }),
  pipe: new THREE.MeshStandardMaterial({ color: PALETTE.pipe, emissive: 0x22bba4, emissiveIntensity: 0.35, roughness: 0.4 }),
  selected: new THREE.MeshStandardMaterial({ color: PALETTE.selected, emissive: 0x28d2b9, emissiveIntensity: 0.3, transparent: true, opacity: 0.35 }),
};

const initialModules = [
  { id: "factory", type: "factory", x: -8, z: -2 },
  { id: "solar", type: "solar", x: -4, z: -10 },
  { id: "generation", type: "generation", x: -10, z: -8 },
  { id: "storage", type: "storage", x: 6, z: -4 },
  { id: "grid", type: "grid", x: -10, z: 8 },
  { id: "charge", type: "charge", x: 2, z: 8 },
  { id: "compute", type: "compute", x: 8, z: 4 },
];

function box(g, size, pos, mat = materials.white) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  m.position.set(...pos);
  m.castShadow = true; m.receiveShadow = true;
  g.add(m); return m;
}

function cyl(g, r, h, pos, mat = materials.side, seg = 24) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat);
  m.position.set(...pos);
  m.castShadow = true; m.receiveShadow = true;
  g.add(m); return m;
}

function cone(g, r, h, pos, mat = materials.tree) {
  const m = new THREE.Mesh(new THREE.ConeGeometry(r, h, 6), mat);
  m.position.set(...pos);
  m.castShadow = true;
  g.add(m); return m;
}

function sphere(g, r, pos, mat = materials.bush) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 8, 6), mat);
  m.position.set(...pos);
  m.castShadow = true;
  g.add(m); return m;
}



function addGreen(group, count = 6) {
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const dist = 1.2 + Math.random() * 0.8;
    const rx = Math.cos(angle) * dist;
    const rz = Math.sin(angle) * dist;
    const r = Math.random();
    if (r < 0.4) {
      cone(group, 0.2 + Math.random() * 0.15, 0.6 + Math.random() * 0.5, [rx, 0.35 + Math.random() * 0.2, rz], Math.random() > 0.5 ? materials.tree : materials.treeLight);
    } else if (r < 0.75) {
      sphere(group, 0.15 + Math.random() * 0.12, [rx, 0.15, rz], materials.bush);
    } else {
      box(group, [0.3, 0.04, 0.3], [rx, 0.02, rz], materials.grass);
    }
  }
}

function makeNameLabel(text) {
  const c = document.createElement("canvas");
  c.width = 300; c.height = 44;
  const ctx = c.getContext("2d");
  ctx.font = "bold 22px sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillStyle = "#556677";
  ctx.fillText(text, 150, 22);
  const t = new THREE.CanvasTexture(c);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthTest: false }));
  s.scale.set(2.4, 0.36, 1); s.position.set(0, -0.1, 0);
  return s;
}

function buildModule(type) {
  const group = new THREE.Group();
  const pad = new THREE.Mesh(new THREE.CylinderGeometry(HEX_R * 0.98, HEX_R * 0.98, 0.08, 6), materials.side);
  pad.position.y = 0.04;
  pad.receiveShadow = true;
  group.add(pad);
  const info = MODULE_TYPES[type];
  if (info) group.add(makeNameLabel(info.title));

  if (type === "factory") {
    box(group, [2.6, 0.95, 1.6], [-0.2, 0.55, 0], materials.white);
    box(group, [2.9, 0.28, 1.9], [-0.2, 1.2, 0], materials.dark);
    for (let i = 0; i < 3; i++) cyl(group, 0.12, 1.25, [-1.0 + i * 0.5, 1.45, -0.5], materials.side, 16);
    for (let i = 0; i < 4; i++) box(group, [0.07, 0.3, 0.3], [1.15, 0.68, -0.6 + i * 0.4], materials.glass);
    box(group, [1.8, 0.06, 1.0], [0, 0.12, 1.4], materials.grass);
  } else if (type === "solar") {
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        const p = box(group, [0.65, 0.07, 0.48], [-0.75 + col * 0.75, 0.32, -0.55 + row * 0.55], materials.solar);
        p.rotation.x = -0.26;
        p.userData.part = "solarPanel";
      }
    }
    box(group, [2.2, 0.05, 1.6], [0, 0.08, 0.2], materials.grass);
  } else if (type === "storage") {
    const stgMat = new THREE.MeshStandardMaterial({ color: 0x5a7a99, roughness: 0.5 });
    for (let i = 0; i < 3; i++) {
      const b = box(group, [0.52, 1.2, 0.95], [-0.65 + i * 0.68, 0.68, 0], i % 2 ? stgMat : materials.white);
      b.userData.part = "battery";
      box(group, [0.34, 0.07, 0.45], [-0.65 + i * 0.68, 1.0, 0.26], new THREE.MeshStandardMaterial({ color: 0x88bbee, roughness: 0.2, metalness: 0.3 }));
    }
    box(group, [1.6, 0.05, 0.8], [0, 0.1, 1.1], materials.grass);
  } else if (type === "grid") {
    const tower = cyl(group, 0.18, 0.14, [0, 0.25, 0], materials.pipe);
    tower.userData.part = "gridTower";
    const lineMat = new THREE.LineBasicMaterial({ color: 0x8092a0 });
    const pts = [[-0.6,0.16,-0.5],[0,2.4,0],[0.6,0.16,-0.5],[-0.5,1.0,-0.4],[0.5,1.0,-0.4],[-0.3,1.6,-0.2],[0.3,1.6,-0.2]].map(p=>new THREE.Vector3(...p));
    group.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), lineMat));
    box(group, [1.2, 0.05, 0.8], [0, 0.08, 1.1], materials.grass);
  } else if (type === "charge") {
    for (let i = 0; i < 3; i++) {
      box(group, [0.3, 0.9, 0.34], [-0.65 + i * 0.68, 0.52, 0.1], materials.white);
      box(group, [0.2, 0.22, 0.04], [-0.65 + i * 0.68, 0.7, -0.1], materials.glass);
    }
    box(group, [2.2, 0.14, 0.6], [0, 0.2, 0.85], materials.side);
    box(group, [1.4, 0.05, 0.6], [0, 0.1, -1.1], materials.grass);
  } else if (type === "compute" || type === "datacenter") {
    const h = type === "datacenter" ? 2.4 : 1.35;
    box(group, [2.0, h, 1.5], [0, 0.14 + h / 2, 0], materials.white);
    box(group, [1.4, 0.16, 1.1], [0, h + 0.3, 0], materials.side);
    for (let i = 0; i < 5; i++) box(group, [0.06, 0.3, 0.3], [-1.0, 0.7, -0.6 + i * 0.32], materials.glass);
    for (let i = 0; i < 2; i++) cyl(group, 0.2, 0.14, [-0.3 + i * 0.65, h + 0.48, 0], materials.dark, 20);
    box(group, [1.6, 0.05, 1.0], [0, 0.1, 1.2], materials.grass);
  } else if (type === "generation") {
    box(group, [2.0, 0.72, 1.2], [0, 0.45, 0], materials.white);
    cyl(group, 0.3, 1.3, [-0.5, 1.0, -0.28], materials.side, 28);
    cyl(group, 0.22, 1.75, [0.5, 1.25, -0.24], materials.side, 28);
    box(group, [1.4, 0.05, 0.9], [0, 0.1, 1.0], materials.grass);
  }
  addGreen(group, 7);
  return group;
}

function snap(v) { return Math.round(v / GRID_STEP) * GRID_STEP; }
function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

function makePipe(f, t) {
  const len = Math.hypot(t.x - f.x, t.z - f.z);
  const horiz = Math.abs(t.x - f.x) > Math.abs(t.z - f.z);
  const m = new THREE.Mesh(
    new THREE.BoxGeometry(horiz ? len : 0.14, 0.06, horiz ? 0.14 : len),
    materials.pipe,
  );
  m.position.set((f.x + t.x) / 2, 0.16, (f.z + t.z) / 2);
  return m;
}

export function createCampus3D(canvas, onLabels) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xf0f5f9);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xf0f5f9, 45, 90);
  const camera = new THREE.OrthographicCamera(-10, 10, 7, -7, 0.1, 120);
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  let azimuth = -0.72, elevation = 0.82, zoom = 1.02;
  let orbiting = false, draggingModule = false, selectedId = null;
  let pointer = [0, 0], idCounter = 1, flowMultiplier = 1;

  const moduleRoot = new THREE.Group();
  const pipeRoot = new THREE.Group();
  const poolRoot = new THREE.Group();
  const hexRoot = new THREE.Group();
  const selectable = [];

  const hexW = HEX_R * Math.sqrt(3);
  const hexHStep = HEX_R * 1.5;
  const hexColors = [materials.hexWhite, materials.hexLight, materials.hexPale];

  function snapToHexGrid(x, z) {
    const row = Math.round(z / hexHStep);
    const offset = (row % 2) * (hexW / 2);
    const col = Math.round((x - offset) / hexW);
    return { x: col * hexW + offset, z: row * hexHStep, row, col };
  }
  const modules = initialModules.map((item) => { const s = snapToHexGrid(item.x, item.z); return { ...item, x: s.x, z: s.z }; });

  // hexagonal honeycomb floor
  for (let row = -20; row <= 20; row++) {
    for (let col = -20; col <= 20; col++) {
      const x = col * hexW + (row % 2) * (hexW / 2);
      const z = row * hexHStep;
      const idx = (Math.abs(row) + Math.abs(col)) % 3;
      const tile = new THREE.Mesh(new THREE.CylinderGeometry(HEX_R, HEX_R, 0.05, 6), hexColors[idx]);
      tile.position.set(x, -0.03, z);
      tile.receiveShadow = true;
      hexRoot.add(tile);
    }
  }

  scene.add(hexRoot, pipeRoot, poolRoot, moduleRoot);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xa8c8e0, 2.4));
  const sun = new THREE.DirectionalLight(0xffffff, 2.8);
  sun.position.set(-8, 14, 8);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -24; sun.shadow.camera.right = 24;
  sun.shadow.camera.top = 24; sun.shadow.camera.bottom = -24;
  scene.add(sun);

  const poolBase = new THREE.Mesh(new THREE.CylinderGeometry(1.05, 1.05, 0.12, 42), materials.pipe);
  poolBase.position.set(0, 0.14, 0); poolRoot.add(poolBase);
  const poolRing = new THREE.Mesh(new THREE.TorusGeometry(1.14, 0.03, 8, 48), materials.pipe);
  poolRing.rotation.x = Math.PI / 2; poolRing.position.set(0, 0.26, 0); poolRoot.add(poolRing);

  function posCam() {
    const r = 31;
    camera.position.set(Math.sin(azimuth) * Math.cos(elevation) * r, Math.sin(elevation) * r, Math.cos(azimuth) * Math.cos(elevation) * r);
    camera.zoom = zoom; camera.lookAt(0, 0, 0); camera.updateProjectionMatrix();
  }

  function rebuildModules() {
    moduleRoot.clear(); selectable.length = 0;
    modules.forEach((mod) => {
      const g = buildModule(mod.type);
      g.scale.setScalar(1.15);
      g.position.set(mod.x, 0, mod.z);
      g.userData = { moduleId: mod.id };
      g.traverse((c) => { if (c.isMesh) { c.userData.moduleId = mod.id; selectable.push(c); } });
      const sel = new THREE.Mesh(new THREE.BoxGeometry(3.8, 0.04, 3.8), materials.selected);
      sel.position.set(0, 0.16, 0); sel.visible = mod.id === selectedId; sel.userData.moduleId = mod.id;
      g.add(sel); moduleRoot.add(g);
    });
    rebuildPipes();
  }

  function rebuildPipes() {
    pipeRoot.clear();
    const pool = { x: 0, z: 0 };
    modules.forEach((mod) => {
      const corner = { x: mod.x, z: 0 };
      pipeRoot.add(makePipe(corner, mod));
      pipeRoot.add(makePipe(pool, corner));
    });
  }

  function moduleAtPtr(e) {
    const rect = canvas.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const hit = raycaster.intersectObjects(selectable, false)[0];
    return hit ? modules.find((m) => m.id === hit.object.userData.moduleId) : null;
  }

  function groundPt(e) {
    const rect = canvas.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const pt = new THREE.Vector3();
    raycaster.ray.intersectPlane(groundPlane, pt);
    return { x: clamp(snap(pt.x), -GRID_LIMIT, GRID_LIMIT), z: clamp(snap(pt.z), -GRID_LIMIT, GRID_LIMIT) };
  }

  function select(id) {
    selectedId = id;
    moduleRoot.children.forEach((g) => { g.children[g.children.length - 1].visible = g.userData.moduleId === selectedId; });
  }

  function resize() {
    const w = Math.max(1, canvas.clientWidth), h = Math.max(1, canvas.clientHeight);
    renderer.setSize(w, h, false);
    const a = w / h;
    camera.left = -9 * a; camera.right = 9 * a; camera.top = 9; camera.bottom = -9;
    camera.updateProjectionMatrix();
  }

  function updateLabels() {
    if (!onLabels) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const labels = {};
    modules.forEach((mod) => {
      const t = MODULE_TYPES[mod.type] || MODULE_TYPES.factory;
      const a = new THREE.Vector3(mod.x, 2.2, mod.z).project(camera);
      const x = (a.x * 0.5 + 0.5) * w;
      const y = (-a.y * 0.5 + 0.5) * h;
      labels[mod.id] = { x: clamp(x, 68, w - 68), y: clamp(y, 42, h - 26), visible: mod.id === selectedId && a.z > -1 && a.z < 1, title: `${t.title} · ${t.category}`, metric: t.metric, note: t.note };
    });
    onLabels(labels);
  }

  canvas.addEventListener("pointerdown", (e) => {
    const mod = moduleAtPtr(e); pointer = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId);
    if (mod) { select(mod.id); draggingModule = true; return; }
    orbiting = true;
  });

  canvas.addEventListener("pointermove", (e) => {
    if (draggingModule && selectedId) {
      const mod = modules.find((m) => m.id === selectedId); if (!mod) return;
      const pt = groundPt(e); const s = snapToHexGrid(pt.x, pt.z); mod.x = s.x; mod.z = s.z;
      const g = moduleRoot.children.find((c) => c.userData.moduleId === selectedId);
      if (g) g.position.set(mod.x, 0, mod.z); rebuildPipes(); return;
    }
    if (!orbiting) return;
    azimuth -= (e.clientX - pointer[0]) * 0.005;
    elevation = clamp(elevation + (e.clientY - pointer[1]) * 0.003, 0.48, 1.18);
    pointer = [e.clientX, e.clientY]; posCam();
  });

  canvas.addEventListener("pointerup", () => { draggingModule = false; orbiting = false; });

  canvas.addEventListener("wheel", (e) => { e.preventDefault(); zoom = clamp(zoom - e.deltaY * 0.0007, 0.62, 1.45); posCam(); }, { passive: false });

  let frame = 0;
  function renderLoop(time) {
    materials.pipe.emissiveIntensity = 0.25 + flowMultiplier + Math.sin(time * 0.004) * 0.1;
    poolRing.rotation.z += 0.01 * flowMultiplier;
    updateLabels(); renderer.render(scene, camera); frame = requestAnimationFrame(renderLoop);
  }

  posCam(); resize(); rebuildModules(); select("factory"); renderLoop(0);
  const observer = new ResizeObserver(resize); observer.observe(canvas);

  return {
    addModule(type = "datacenter") {
      const t = MODULE_TYPES[type] ? type : "datacenter";
      const id = `${t}-${idCounter++}`;
      modules.push({ id, type: t, x: clamp(snap(-2 + idCounter * 2), -GRID_LIMIT, GRID_LIMIT), z: clamp(snap(2 + idCounter), -GRID_LIMIT, GRID_LIMIT) });
      rebuildModules(); select(id);
    },
    deleteSelected() {
      if (!selectedId || modules.length <= 1) return;
      const i = modules.findIndex((m) => m.id === selectedId);
      if (i >= 0) modules.splice(i, 1); selectedId = modules[0]?.id || null;
      rebuildModules(); if (selectedId) select(selectedId);
    },
    applyEnergyState(p = {}) {
      flowMultiplier = p.optimized ? 0.5 : 0.22;
      MODULE_TYPES.grid.metric = p.gridImport || (p.optimized ? "8 MW" : "0.00 kW");
      MODULE_TYPES.grid.note = p.optimized ? "已按批准方案执行" : "缺口由外部电网补足";
      MODULE_TYPES.solar.metric = p.generation || MODULE_TYPES.solar.metric;
      MODULE_TYPES.storage.metric = p.storage || (p.optimized ? "SOC 79%" : "SOC 20%");
      MODULE_TYPES.storage.note = p.storageFlow || (p.optimized ? "充放电调峰中" : "待命 0.00 kW");
      MODULE_TYPES.factory.metric = p.load || "25 MW";
      MODULE_TYPES.factory.note = p.optimized ? "已纳入 V2 调度" : "OpenCEM 实测负载";
      rebuildModules(); if (selectedId) select(selectedId);
      const pvVal = parseFloat((p.generation || "0").replace(/[^0-9.]/g, "")) || 0;
      const gridVal = parseFloat((p.gridImport || "0").replace(/[^0-9.]/g, "")) || 0;
      const loadVal = parseFloat((p.load || "0").replace(/[^0-9.]/g, "")) || 0;
      const socMatch = (p.storage || "").match(/(\d+)/);
      const socVal = socMatch ? parseInt(socMatch[1]) : 55;
      moduleRoot.traverse((child) => {
        if (!child.userData.part || !child.isMesh) return;
        if (child.userData.part === "solarPanel") {
          const intensity = Math.min(0.7, pvVal / 3);
          if (!child._origMat) child._origMat = child.material;
          child.material = child._origMat.clone();
          child.material.emissive = new THREE.Color(0x2dd4bf);
          child.material.emissiveIntensity = intensity;
        }
        if (child.userData.part === "battery") {
          const ratio = socVal / 100;
          if (!child._origMat) child._origMat = child.material;
          child.material = child._origMat.clone();
          child.material.color = new THREE.Color(`rgb(${Math.floor((1-ratio)*100+30)},${Math.floor(ratio*120+60)},180)`);
        }
        if (child.userData.part === "gridTower") {
          const intensity = gridVal > 0.01 ? Math.min(0.9, gridVal / 3 + 0.2) : 0.05;
          if (!child._origMat) child._origMat = child.material;
          child.material = child._origMat.clone();
          child.material.emissiveIntensity = intensity;
        }
      });
      // Solar generation glow pulse
      const solarPos = modules.find(m => m.type === "solar");
      if (solarPos) {
        let glow = scene.children.find(c => c.userData?.isSolarGlow);
        if (!glow) {
          glow = new THREE.Mesh(new THREE.SphereGeometry(0.6, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffdd33, transparent: true, opacity: 0 }));
          glow.userData = { isSolarGlow: true };
          glow.position.set(solarPos.x, 2.2, solarPos.z);
          scene.add(glow);
        }
        const targetOp = pvVal > 0.01 ? Math.min(0.6, pvVal / 4) : 0;
        glow.material.opacity += (targetOp - glow.material.opacity) * 0.1;
        const s = 1 + Math.sin(Date.now() * 0.004) * 0.3;
        glow.scale.set(s, s, s);
      }
      // Energy flow: solar -> storage particles
      if (pvVal > 0.01) {
        const storagePos = modules.find(m => m.type === "storage");
        if (solarPos && storagePos) {
          let particles = scene.userData.flowParticles;
          if (!particles) { particles = []; scene.userData.flowParticles = particles; }
          if (particles.length < 12) {
            const mat = new THREE.MeshBasicMaterial({ color: 0xffdd33 });
            const p = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 8), mat);
            p.userData = { t: Math.random(), speed: 0.6 + Math.random() * 0.5 };
            scene.add(p); particles.push(p);
          }
          particles.forEach(p => {
            p.userData.t += p.userData.speed * 0.016;
            if (p.userData.t > 1) p.userData.t = 0;
            const t = p.userData.t;
            p.position.set(
              solarPos.x + (storagePos.x - solarPos.x) * t,
              1.0 + Math.sin(t * Math.PI) * 0.8,
              solarPos.z + (storagePos.z - solarPos.z) * t
            );
          });
        }
      } else {
        (scene.userData.flowParticles || []).forEach(p => scene.remove(p));
        scene.userData.flowParticles = null;
      }
    },
    reset() { azimuth = -0.72; elevation = 0.82; zoom = 1.02; posCam(); },
    resize, destroy() { cancelAnimationFrame(frame); observer.disconnect(); renderer.dispose(); },
  };
}
