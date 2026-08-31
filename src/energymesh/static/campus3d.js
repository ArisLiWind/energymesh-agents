import * as THREE from "/static/vendor/three.module.min.js";

const FLOW_DEFS = [
  { id: "solar_load", from: "solar", to: "load", title: "自发自用", color: 0x2ac7a5 },
  { id: "solar_storage", from: "solar", to: "storage", title: "光伏充电", color: 0x2ac7a5 },
  { id: "storage_load", from: "storage", to: "load", title: "储能放电", color: 0x20a8bf },
  { id: "grid_load", from: "grid", to: "load", title: "电网购电", color: 0xd79a31 },
  { id: "solar_grid", from: "solar", to: "grid", title: "余电上网", color: 0x64b980 },
];

const MODULES = [
  { id: "solar", title: "发电格", device: "屋顶光伏", metric: "-- kW", note: "限发 --", x: -3.6, z: 1.35, kind: "solar" },
  { id: "storage", title: "储能格", device: "电池 + PCS", metric: "SOC --", note: "待机", x: -.9, z: 1.35, kind: "storage" },
  { id: "load", title: "用电格", device: "车间 + 算力", metric: "-- kW", note: "连续负荷", x: 1.8, z: 1.35, kind: "load" },
  { id: "grid", title: "电网格", device: "公共电网", metric: "-- kW", note: "购电/上网", x: -3.6, z: -1.35, kind: "grid" },
  { id: "factory", title: "生产车间", device: "不可中断", metric: "运行中", note: "用电子格", x: -.9, z: -1.35, kind: "factory" },
  { id: "charge", title: "柔性负荷", device: "充电区", metric: "可移峰", note: "Agent 可调整", x: 1.8, z: -1.35, kind: "charge" },
];

const FLOW_PATHS = {
  solar_load: [[-3.9, 1.35], [-1.55, 1.35], [-.05, .35], [2.65, -.25]],
  solar_storage: [[-3.9, 1.35], [-2.25, .65], [-.95, .55]],
  storage_load: [[-.95, .55], [.6, .55], [2.65, -.25]],
  grid_load: [[-3.85, -2.05], [-1.15, -2.05], [.85, -1.1], [2.65, -.25]],
  solar_grid: [[-3.9, 1.35], [-5.05, .15], [-3.85, -2.05]],
};

const MUTED = 0xcbd5df;
const INK = 0x1f2937;
const ZERO_FLOW = { solar_load: 0, solar_storage: 0, storage_load: 0, grid_load: 0, solar_grid: 0, curtail: 0 };

function makeCanvasTexture(draw) {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 168;
  const ctx = canvas.getContext("2d");
  draw(ctx, canvas);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeLabel(def) {
  const texture = makeCanvasTexture((ctx) => {
    ctx.clearRect(0, 0, 640, 168);
    ctx.shadowColor = "rgba(15, 23, 42, .12)";
    ctx.shadowBlur = 18;
    ctx.fillStyle = "rgba(255,255,255,.96)";
    ctx.fillRect(30, 20, 580, 118);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(190, 203, 215, .8)";
    ctx.strokeRect(30.5, 20.5, 579, 117);
    ctx.fillStyle = "#1f2937";
    ctx.font = "700 26px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.title, 54, 58);
    ctx.fillStyle = "#667085";
    ctx.font = "500 18px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.device || "", 54, 88);
    ctx.fillStyle = def.kind === "solar" ? "#17a67f" : def.kind === "grid" ? "#b8751d" : "#2563eb";
    ctx.font = "800 22px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.metric || "--", 54, 120);
    ctx.fillStyle = "#7c8794";
    ctx.font = "500 16px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.note || "", 260, 120);
  });
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
  sprite.scale.set(2.55, .67, 1);
  sprite.userData.texture = texture;
  return sprite;
}

function updateLabel(sprite, def) {
  sprite.material.map?.dispose?.();
  sprite.material.map = makeCanvasTexture((ctx) => {
    ctx.clearRect(0, 0, 640, 168);
    ctx.shadowColor = "rgba(15, 23, 42, .12)";
    ctx.shadowBlur = 18;
    ctx.fillStyle = "rgba(255,255,255,.97)";
    ctx.fillRect(30, 20, 580, 118);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(190, 203, 215, .8)";
    ctx.strokeRect(30.5, 20.5, 579, 117);
    ctx.fillStyle = "#111827";
    ctx.font = "700 26px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.title, 54, 58);
    ctx.fillStyle = "#667085";
    ctx.font = "500 18px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.device || "", 54, 88);
    ctx.fillStyle = def.kind === "solar" ? "#17a67f" : def.kind === "grid" ? "#b8751d" : "#2563eb";
    ctx.font = "800 22px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.metric || "--", 54, 120);
    ctx.fillStyle = "#7c8794";
    ctx.font = "500 16px Inter, PingFang SC, sans-serif";
    ctx.fillText(def.note || "", 260, 120);
  });
  sprite.material.needsUpdate = true;
}

function box(size, color = 0xffffff) {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(size[0], size[1], size[2]),
    new THREE.MeshStandardMaterial({ color, roughness: .78, metalness: .02 }),
  );
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({ color: 0xaeb9c5, transparent: true, opacity: .8 }),
  );
  group.add(edges);
  return group;
}

function pad(w, d, color = 0xf2f5f8) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(w, .06, d),
    new THREE.MeshStandardMaterial({ color, roughness: .92 }),
  );
  mesh.position.y = -.04;
  mesh.receiveShadow = true;
  return mesh;
}

function makeModule(def) {
  const group = new THREE.Group();
  group.position.set(def.x, 0, def.z);
  group.userData = { ...def };
  const baseColor = def.kind === "solar" ? 0xdff8ef : def.kind === "grid" ? 0xf7f0e5 : def.kind === "storage" ? 0xe9efff : 0xf5f7fa;
  group.add(pad(def.kind === "load" ? 1.75 : 1.38, def.kind === "load" ? 1.32 : 1.1, baseColor));

  if (def.kind === "solar") {
    for (let i = 0; i < 6; i += 1) {
      const panel = box([.46, .05, .62], 0xecfaff);
      panel.position.set(-.48 + (i % 3) * .5, .1, -.22 + Math.floor(i / 3) * .52);
      panel.rotation.y = -.18;
      group.add(panel);
    }
  } else if (def.kind === "grid") {
    const mast = box([.16, 1.05, .16], 0xffffff);
    mast.position.y = .53;
    const top = box([.9, .12, .12], 0xffffff);
    top.position.y = 1.1;
    const cross = box([.12, .12, .82], 0xffffff);
    cross.position.y = .86;
    group.add(mast, top, cross);
  } else if (def.kind === "storage") {
    const shell = box([.82, 1.35, .56], 0xffffff);
    shell.position.y = .68;
    shell.name = "storageShell";
    group.add(shell);
    const glass = new THREE.Mesh(
      new THREE.BoxGeometry(.7, 1.14, .04),
      new THREE.MeshBasicMaterial({ color: 0xdffbff, transparent: true, opacity: .42 }),
    );
    glass.position.set(0, .68, -.285);
    group.add(glass);
    const fill = new THREE.Mesh(
      new THREE.BoxGeometry(.62, 1, .05),
      new THREE.MeshStandardMaterial({ color: 0xb6f023, transparent: true, opacity: .86, roughness: .38, emissive: 0x315c08, emissiveIntensity: .18 }),
    );
    fill.name = "socFill";
    fill.position.set(0, .12, -.32);
    fill.scale.y = .02;
    group.add(fill);
  } else if (def.kind === "load") {
    const hall = box([1.26, .68, .96], 0xffffff);
    hall.position.y = .35;
    const tower = box([.48, 1.36, .54], 0xf8fafc);
    tower.position.set(-.42, .7, -.18);
    const server = box([.4, 1.05, .44], 0xffffff);
    server.position.set(.46, .54, .22);
    group.add(hall, tower, server);
  } else {
    const unit = box([.8, .72, .72], 0xffffff);
    unit.position.y = .38;
    group.add(unit);
  }

  const label = makeLabel(def);
  label.position.set(0, 1.64, 0);
  label.name = "label";
  label.visible = false;
  group.add(label);
  return group;
}

function routePoints(path) {
  return path.map(([x, z]) => new THREE.Vector3(x, .13, z));
}

function routedPoints(modules, fromId, toId, routeId = "") {
  const from = modules.get(fromId)?.position || new THREE.Vector3();
  const to = modules.get(toId)?.position || new THREE.Vector3();
  const midX = (from.x + to.x) / 2;
  const sameRow = Math.abs(from.z - to.z) < .01;
  const laneMap = {
    solar_load: .22,
    solar_storage: -.18,
    storage_load: -.18,
    grid_load: -.28,
    solar_grid: .34,
  };
  const laneOffset = sameRow ? (laneMap[routeId] || 0) : (laneMap[routeId] || (from.z < to.z ? -.34 : .34));
  return [
    new THREE.Vector3(from.x, .16, from.z),
    new THREE.Vector3(midX, .16, from.z + laneOffset),
    new THREE.Vector3(midX, .16, to.z + laneOffset),
    new THREE.Vector3(to.x, .16, to.z),
  ];
}

function makeRoute(def, dashed = false) {
  const points = routePoints(FLOW_PATHS[def.id]);
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = dashed
    ? new THREE.LineDashedMaterial({ color: def.color, dashSize: .18, gapSize: .13, transparent: true, opacity: .38 })
    : new THREE.LineBasicMaterial({ color: def.color, transparent: true, opacity: .9 });
  const line = new THREE.Line(geometry, material);
  line.visible = true;
  if (dashed) line.computeLineDistances();
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 72, dashed ? .014 : .052, 8, false),
    new THREE.MeshBasicMaterial({ color: def.color, transparent: true, opacity: dashed ? .16 : .42 }),
  );

  const particles = Array.from({ length: dashed ? 4 : 6 }, () => {
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(dashed ? .032 : .036, 12, 12),
      new THREE.MeshBasicMaterial({ color: def.color, transparent: true, opacity: dashed ? .48 : .78 }),
    );
    return dot;
  });
  const group = new THREE.Group();
  group.add(tube, line, ...particles);
  group.visible = !dashed;
  group.userData = { def, points, line, tube, particles, power: 0, preview: dashed, progress: Math.random() };
  return group;
}

function rebuildRouteGeometry(route, points) {
  route.userData.points = points;
  route.userData.line.geometry.dispose();
  route.userData.line.geometry = new THREE.BufferGeometry().setFromPoints(points);
  if (route.userData.line.computeLineDistances) route.userData.line.computeLineDistances();
  if (route.userData.tube) {
    route.userData.tube.geometry.dispose();
    route.userData.tube.geometry = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 72, route.userData.preview ? .014 : .052, 8, false);
  }
}

function valueNumber(raw) {
  const match = String(raw || "").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : 0;
}

function pointAlong(points, t) {
  if (points.length === 1) return points[0].clone();
  const lengths = [];
  let total = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    const len = points[i].distanceTo(points[i + 1]);
    lengths.push(len);
    total += len;
  }
  let target = ((t % 1) + 1) % 1 * total;
  for (let i = 0; i < lengths.length; i += 1) {
    if (target <= lengths[i]) return points[i].clone().lerp(points[i + 1], target / lengths[i]);
    target -= lengths[i];
  }
  return points[points.length - 1].clone();
}

function setRoutePower(route, power, maxPower, previewActive = false) {
  route.userData.power = Math.max(0, Number(power) || 0);
  const active = route.userData.power > .05;
  const preview = route.userData.preview;
  const opacity = active ? (preview ? .58 : previewActive ? .24 : .9) : 0;
  route.userData.line.material.color.set(active ? route.userData.def.color : MUTED);
  route.userData.line.material.opacity = opacity;
  route.userData.line.material.linewidth = 1 + Math.min(8, route.userData.power / Math.max(maxPower, 1) * 8);
  if (route.userData.tube) {
    route.userData.tube.material.color.set(active ? route.userData.def.color : MUTED);
    route.userData.tube.material.opacity = active ? (preview ? .16 : previewActive ? .08 : .3) : 0;
    const scale = 1 + Math.min(1.9, route.userData.power / Math.max(maxPower, 1) * 1.9);
    route.userData.tube.scale.setScalar(scale);
  }
  route.userData.particles.forEach((dot) => {
    dot.material.color.set(active ? route.userData.def.color : MUTED);
    dot.material.opacity = active ? (preview ? .58 : previewActive ? .2 : .9) : 0;
    const scale = .72 + Math.min(1.8, route.userData.power / Math.max(maxPower, 1) * 1.8);
    dot.scale.setScalar(scale);
  });
}

function buildFlowState(state = {}) {
  const load = valueNumber(state.load);
  const generation = valueNumber(state.generation);
  const gridImport = valueNumber(state.gridImport);
  const storageFlowText = String(state.storageFlow || "");
  const storagePower = valueNumber(storageFlowText);
  const isCharging = storageFlowText.includes("充");
  const isDischarging = storageFlowText.includes("放") || state.optimized;
  const rawCurtail = state.curtailKw == null ? Math.max(0, generation - load - (isCharging ? storagePower : 0)) : Number(state.curtailKw);
  const curtailKw = Math.max(0, rawCurtail);
  const solarStorage = isCharging ? storagePower : 0;
  const storageLoad = isDischarging ? storagePower : 0;
  const gridLoad = Math.max(0, gridImport);
  const solarLoad = Math.max(0, Math.min(generation - solarStorage - curtailKw, load - storageLoad - gridLoad));
  const solarGrid = Math.max(0, Number(state.exportKw ?? 0));
  return { solar_load: solarLoad, solar_storage: solarStorage, storage_load: storageLoad, grid_load: gridLoad, solar_grid: solarGrid, curtail: curtailKw };
}

export function createCampus3D(canvas, onLabels) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0xf8fafc, 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf8fafc);
  const camera = new THREE.OrthographicCamera(-6, 6, 3.6, -3.6, .1, 100);
  camera.position.set(5.8, 5.4, 6.4);
  camera.lookAt(0, 0, 0);
  const cameraTarget = new THREE.Vector3(0, 0, 0);
  let zoom = 1.22;

  scene.add(new THREE.AmbientLight(0xffffff, 2.25));
  const light = new THREE.DirectionalLight(0xffffff, 1.9);
  light.position.set(4, 8, 5);
  light.castShadow = true;
  scene.add(light);

  const grid = new THREE.GridHelper(160, 160, 0xdde5ee, 0xf0f3f7);
  grid.position.y = -.055;
  scene.add(grid);

  const modules = new Map();
  MODULES.forEach((def) => {
    const module = makeModule(def);
    modules.set(def.id, module);
    scene.add(module);
  });

  const liveRoutes = new Map();
  const previewRoutes = new Map();
  FLOW_DEFS.forEach((def) => {
    const route = makeRoute(def, false);
    liveRoutes.set(def.id, route);
    scene.add(route);
    const preview = makeRoute(def, true);
    previewRoutes.set(def.id, preview);
    scene.add(preview);
  });
  let selectedId = "load";
  let dragging = null;
  let previewFlow = null;
  let liveFlow = {};
  const pointer = new THREE.Vector2();
  const raycaster = new THREE.Raycaster();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hit = new THREE.Vector3();
  let running = true;

  function syncRoutesToModules() {
    liveRoutes.forEach((route) => {
      const { from, to } = route.userData.def;
      rebuildRouteGeometry(route, routedPoints(modules, from, to, route.userData.def.id));
    });
    previewRoutes.forEach((route) => {
      const { from, to } = route.userData.def;
      rebuildRouteGeometry(route, routedPoints(modules, from, to, route.userData.def.id));
    });
  }

  function resize() {
    const { clientWidth, clientHeight } = canvas;
    renderer.setSize(clientWidth, clientHeight, false);
    const aspect = clientWidth / Math.max(clientHeight, 1);
    camera.left = -4.95 * aspect;
    camera.right = 4.95 * aspect;
    camera.top = 4.55;
    camera.bottom = -4.55;
    camera.zoom = zoom;
    camera.updateProjectionMatrix();
  }

  function updateLabels() {
    const labels = {};
    const rect = canvas.getBoundingClientRect();
    modules.forEach((module, id) => {
      const world = module.position.clone();
      world.y = 1.38;
      world.project(camera);
      labels[id] = {
        x: (world.x * .5 + .5) * rect.width + (["solar", "grid"].includes(id) ? -46 : 46),
        y: (-world.y * .5 + .5) * rect.height,
        visible: ["solar", "storage", "load", "grid"].includes(id),
        placement: ["storage", "grid"].includes(id) ? "below" : "above",
        title: module.userData.title,
        device: module.userData.device,
        metric: module.userData.metric,
        note: module.userData.note,
      };
    });
    onLabels?.(labels);
  }

  function animateRoute(route, elapsed) {
    const power = route.userData.power || 0;
    const active = power > .05;
    const speed = active ? .12 + Math.min(.72, power / 24) : 0;
    route.userData.particles.forEach((dot, index) => {
      const t = route.userData.progress + elapsed * speed + index / route.userData.particles.length;
      dot.position.copy(pointAlong(route.userData.points, t));
      dot.visible = active;
    });
  }

  function render(elapsed = 0) {
    resize();
    const all = [...liveRoutes.values(), ...previewRoutes.values()];
    all.forEach((route) => animateRoute(route, elapsed));
    updateLabels();
    renderer.render(scene, camera);
  }

  function loop(now = 0) {
    if (!running) return;
    render(now / 1000);
    window.requestAnimationFrame(loop);
  }

  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects([...modules.values()], true);
    if (!hits.length) return null;
    let object = hits[0].object;
    while (object && !object.userData.id) object = object.parent;
    return object || null;
  }

  canvas.addEventListener("pointerdown", (event) => {
    const module = pick(event);
    selectedId = module?.userData.id || selectedId;
    dragging = module || { pan: true, x: event.clientX, y: event.clientY };
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    if (dragging.pan) {
      const dx = (event.clientX - dragging.x) / 95 / zoom;
      const dz = (event.clientY - dragging.y) / 95 / zoom;
      cameraTarget.x -= dx;
      cameraTarget.z -= dz;
      camera.position.x -= dx;
      camera.position.z -= dz;
      camera.lookAt(cameraTarget);
      dragging.x = event.clientX;
      dragging.y = event.clientY;
      return;
    }
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    raycaster.ray.intersectPlane(plane, hit);
    dragging.position.x = hit.x;
    dragging.position.z = hit.z;
    syncRoutesToModules();
  });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom = THREE.MathUtils.clamp(zoom * (event.deltaY > 0 ? .92 : 1.08), .62, 2.6);
    resize();
  }, { passive: false });
  window.addEventListener("pointerup", () => { dragging = null; });
  window.addEventListener("resize", render);

  function syncModules(state = {}) {
    if (state.noData) {
      const waitingValues = {
        solar: { metric: "-- kW", note: "等待 CSV" },
        storage: { metric: "SOC --", note: "等待 CSV 接入" },
        load: { metric: "-- kW", note: "等待 CSV" },
        grid: { metric: "-- kW", note: "0 kW 熄灭" },
      };
      Object.entries(waitingValues).forEach(([id, value]) => {
        const module = modules.get(id);
        if (!module) return;
        module.userData.metric = value.metric;
        module.userData.note = value.note;
        const label = module.getObjectByName("label");
        if (label) updateLabel(label, module.userData);
      });
      const socFill = modules.get("storage")?.getObjectByName("socFill");
      if (socFill) {
        socFill.scale.y = .02;
        socFill.position.y = .2;
        socFill.material.color.set(0xcbd5df);
      }
      return;
    }
    const load = valueNumber(state.load);
    const generation = valueNumber(state.generation);
    const gridImport = valueNumber(state.gridImport);
    const storage = valueNumber(state.storage);
    const curtailKw = state.curtailKw ?? liveFlow.curtail ?? 0;
    const values = {
      solar: { metric: `${generation.toFixed(1)} kW`, note: `限发 ${Number(curtailKw || 0).toFixed(1)} kW` },
      storage: { metric: storage ? `SOC ${storage.toFixed(0)}%` : "SOC --", note: state.storageFlow || "待机" },
      load: { metric: `${load.toFixed(1)} kW`, note: "正在用电" },
      grid: { metric: `${gridImport.toFixed(1)} kW`, note: gridImport > .05 ? "购电中" : "0 kW 熄灭" },
    };
    Object.entries(values).forEach(([id, value]) => {
      const module = modules.get(id);
      if (!module) return;
      module.userData.metric = value.metric;
      module.userData.note = value.note;
      const label = module.getObjectByName("label");
      if (label) updateLabel(label, module.userData);
    });
    const socFill = modules.get("storage")?.getObjectByName("socFill");
    if (socFill) {
      const socRatio = THREE.MathUtils.clamp(Number(state.socPercent ?? storage) / 100, 0, 1);
      const fillHeight = Math.max(.03, socRatio * 1.04);
      socFill.scale.y = fillHeight;
      socFill.position.y = .12 + fillHeight / 2;
      socFill.material.color.set(socRatio > .55 ? 0xb6f023 : socRatio > .28 ? 0xf1d33b : 0xef6f62);
      socFill.material.emissive.set(String(state.storageFlow || "").includes("充") ? 0x166c82 : 0x315c08);
    }
  }

  function applyFlows(flow, preview = null) {
    const maxPower = Math.max(1, ...Object.values(flow || {}), ...Object.values(preview || {}));
    liveRoutes.forEach((route, id) => setRoutePower(route, flow[id] || 0, maxPower, Boolean(preview)));
    previewRoutes.forEach((route, id) => {
      route.visible = Boolean(preview);
      route.userData.line.visible = Boolean(preview);
      route.userData.tube.visible = Boolean(preview);
      setRoutePower(route, preview?.[id] || 0, maxPower, false);
    });
  }

  function applyEnergyState(state = {}) {
    liveFlow = state.flows || buildFlowState(state);
    previewFlow = state.previewFlows || null;
    syncModules({ ...state, curtailKw: liveFlow.curtail });
    applyFlows(liveFlow, previewFlow);
  }

  function previewEnergyState(nextState = {}) {
    previewFlow = nextState.flows || buildFlowState(nextState);
    applyFlows(liveFlow, previewFlow);
  }

  function adoptPreview() {
    if (!previewFlow) return;
    liveFlow = { ...previewFlow };
    previewFlow = null;
    applyFlows(liveFlow, null);
  }

  function addModule(type = "factory") {
    const id = `${type}-${modules.size + 1}`;
    const def = { id, title: type === "storage" ? "新增储能" : type === "generation" ? "新增发电" : "新增用电", device: "拖动定位", metric: "待接入", note: "未进入主调度", x: 4.2, z: -2.4 + (modules.size % 3) * .7, kind: type };
    const module = makeModule(def);
    modules.set(id, module);
    scene.add(module);
    selectedId = id;
    syncRoutesToModules();
  }

  function deleteSelected() {
    const module = modules.get(selectedId);
    if (!module || ["grid", "solar", "storage", "load"].includes(selectedId)) return;
    scene.remove(module);
    modules.delete(selectedId);
    selectedId = "load";
    syncRoutesToModules();
  }

  function reset() {
    MODULES.forEach((def) => {
      const module = modules.get(def.id);
      if (module) module.position.set(def.x, 0, def.z);
    });
    cameraTarget.set(0, 0, 0);
    camera.position.set(5.8, 5.4, 6.4);
    camera.lookAt(cameraTarget);
    zoom = 1.22;
    selectedId = "load";
    syncRoutesToModules();
  }

  function destroy() {
    running = false;
    window.removeEventListener("resize", render);
    renderer.dispose();
  }

  applyEnergyState({ load: "-- kW", generation: "-- kW", storage: "SOC --", storageFlow: "等待 CSV 接入", gridImport: "-- kW", noData: true, flows: ZERO_FLOW });
  syncRoutesToModules();
  window.requestAnimationFrame(loop);
  return { addModule, deleteSelected, applyEnergyState, previewEnergyState, adoptPreview, reset, resize, destroy };
}
