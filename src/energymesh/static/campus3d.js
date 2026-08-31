import * as THREE from "/static/vendor/three.module.min.js";

const FLOW_DEFS = [
  { id: "solar_load", from: "solar", to: "load", title: "自发自用", color: 0x2ac7a5 },
  { id: "solar_storage", from: "solar", to: "storage", title: "光伏充电", color: 0x27bfd0 },
  { id: "storage_load", from: "storage", to: "load", title: "储能放电", color: 0x5b7cff },
  { id: "grid_load", from: "grid", to: "load", title: "电网购电", color: 0xd79a31 },
  { id: "solar_grid", from: "solar", to: "grid", title: "余电上网", color: 0x8fcf70 },
];

const MODULES = [
  { id: "grid", title: "电网格", device: "公共电网", metric: "-- kW", note: "购电/上网", x: -4.15, z: 0, kind: "grid" },
  { id: "solar", title: "发电格", device: "屋顶光伏", metric: "-- kW", note: "限发 --", x: -2.45, z: 1.45, kind: "solar" },
  { id: "storage", title: "储能格", device: "电池 + PCS", metric: "SOC --", note: "待机", x: -.7, z: 1.45, kind: "storage" },
  { id: "load", title: "用电格", device: "数据中心 + 算力", metric: "-- kW", note: "连续负荷", x: 1.35, z: 1.45, kind: "load" },
  { id: "factory", title: "厂房", device: "不可中断负荷", metric: "运行中", note: "主线供电", x: 2.75, z: .1, kind: "factory" },
  { id: "charge", title: "充电站", device: "柔性负荷", metric: "可移峰", note: "主线供电", x: .7, z: -1.25, kind: "charge" },
];

const BUS_Z = -.28;
const BUS_LEFT = -4.55;
const BUS_RIGHT = 3.35;
const BUS_TAP_X = { grid: -4.15, solar: -2.45, storage: -.7, load: 1.35, factory: 2.75, charge: .7 };
const BUS_TAP_Z = { grid: 0, solar: 1.45, storage: 1.45, load: 1.45, factory: .1, charge: -1.25 };
const FLOW_PATHS = {};

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

function makeRouteCurve(points) {
  return new THREE.CatmullRomCurve3(points, false, "centripetal", .25);
}

function tapPoint(id, y = .16, modules = null) {
  const module = modules?.get?.(id);
  return new THREE.Vector3(module?.position.x ?? BUS_TAP_X[id] ?? 0, y, module?.position.z ?? BUS_TAP_Z[id] ?? 0);
}

function busPoint(id, y = .16, modules = null) {
  const module = modules?.get?.(id);
  return new THREE.Vector3(module?.position.x ?? BUS_TAP_X[id] ?? 0, y, BUS_Z);
}

function compactPath(points) {
  return points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || previous.distanceTo(point) > .01;
  });
}

function routedPoints(modules, fromId, toId) {
  const from = modules.get(fromId)?.position || new THREE.Vector3();
  const to = modules.get(toId)?.position || new THREE.Vector3();
  return compactPath([
    new THREE.Vector3(from.x, .16, from.z),
    busPoint(fromId, .16, modules),
    busPoint(toId, .16, modules),
    new THREE.Vector3(to.x, .16, to.z),
  ]);
}

function topologyWirePoints(modules) {
  const points = [
    new THREE.Vector3(BUS_LEFT, .105, BUS_Z),
    new THREE.Vector3(BUS_RIGHT, .105, BUS_Z),
  ];
  modules.forEach((module, id) => {
    points.push(tapPoint(id, .105, modules), busPoint(id, .105, modules));
  });
  return points;
}

function makeTopologyWire(modules) {
  const points = topologyWirePoints(modules);
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const wire = new THREE.LineSegments(
    geometry,
    new THREE.LineBasicMaterial({ color: 0xcbd5df, transparent: true, opacity: .62 }),
  );
  wire.name = "topologyWire";
  return wire;
}

function rebuildTopologyWire(wire, modules) {
  wire.geometry.dispose();
  wire.geometry = new THREE.BufferGeometry().setFromPoints(topologyWirePoints(modules));
}

function makeRoute(def, dashed = false) {
  const points = routePoints(FLOW_PATHS[def.id] || [[0, 0], [.01, 0]]);
  const curve = makeRouteCurve(points);
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = dashed
    ? new THREE.LineDashedMaterial({ color: def.color, dashSize: .18, gapSize: .13, transparent: true, opacity: .38 })
    : new THREE.LineBasicMaterial({ color: def.color, transparent: true, opacity: .9 });
  const line = new THREE.Line(geometry, material);
  line.visible = false;
  if (dashed) line.computeLineDistances();
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 96, dashed ? .012 : .026, 8, false),
    new THREE.MeshBasicMaterial({ color: def.color, transparent: true, opacity: dashed ? .14 : .34 }),
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
  group.userData = { def, points, curve, line, tube, particles, power: 0, preview: dashed, progress: Math.random() };
  return group;
}

function rebuildRouteGeometry(route, points) {
  const curve = makeRouteCurve(points);
  route.userData.points = points;
  route.userData.curve = curve;
  route.userData.line.geometry.dispose();
  route.userData.line.geometry = new THREE.BufferGeometry().setFromPoints(points);
  if (route.userData.line.computeLineDistances) route.userData.line.computeLineDistances();
  if (route.userData.tube) {
    route.userData.tube.geometry.dispose();
    route.userData.tube.geometry = new THREE.TubeGeometry(curve, 96, route.userData.preview ? .012 : .026, 8, false);
  }
}

function valueNumber(raw) {
  const match = String(raw || "").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : 0;
}

function setRoutePower(route, power, maxPower, previewActive = false, previewLine = false) {
  route.userData.power = Math.max(0, Number(power) || 0);
  const active = route.userData.power > .05;
  const preview = route.userData.preview;
  const opacity = 0;
  route.visible = active;
  route.userData.line.visible = false;
  route.userData.line.material.color.set(active ? route.userData.def.color : MUTED);
  route.userData.line.material.opacity = opacity;
  route.userData.line.material.linewidth = 1 + Math.min(8, route.userData.power / Math.max(maxPower, 1) * 8);
  if (route.userData.tube) {
    route.userData.tube.visible = active;
    route.userData.tube.material.color.set(active ? route.userData.def.color : MUTED);
    route.userData.tube.material.opacity = active ? (preview ? 0 : previewLine ? .26 : previewActive ? 0 : .36) : 0;
    route.userData.tube.scale.set(1, 1, 1);
  }
  route.userData.particles.forEach((dot) => {
    dot.material.color.set(active ? route.userData.def.color : MUTED);
    dot.material.opacity = active ? (preview ? 0 : previewLine ? .78 : previewActive ? .12 : .9) : 0;
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
  const topologyWire = makeTopologyWire(modules);
  scene.add(topologyWire);

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
      rebuildRouteGeometry(route, routedPoints(modules, from, to));
    });
    previewRoutes.forEach((route) => {
      const { from, to } = route.userData.def;
      rebuildRouteGeometry(route, routedPoints(modules, from, to));
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
      const kind = module.userData.kind;
      world.y = kind === "storage" ? 1.58 : kind === "grid" ? 1.2 : kind === "solar" ? .46 : kind === "load" ? 1.22 : .88;
      world.project(camera);
      labels[id] = {
        x: (world.x * .5 + .5) * rect.width,
        y: (-world.y * .5 + .5) * rect.height,
        visible: ["solar", "storage", "load", "grid"].includes(id),
        placement: "above",
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
      dot.position.copy(route.userData.curve.getPointAt(((t % 1) + 1) % 1));
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
    dragging = { pan: true, x: event.clientX, y: event.clientY };
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
    liveRoutes.forEach((route, id) => {
      const currentPower = flow[id] || 0;
      const previewPower = preview?.[id] || 0;
      const hasPreview = Boolean(preview);
      const displayPower = hasPreview && previewPower > .05 ? previewPower : currentPower;
      setRoutePower(route, displayPower, maxPower, hasPreview && previewPower <= .05, hasPreview && previewPower > .05);
    });
    previewRoutes.forEach((route, id) => {
      route.visible = false;
      route.userData.line.visible = false;
      route.userData.tube.visible = false;
      setRoutePower(route, 0, maxPower, false);
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
    const nextIndex = Math.max(0, modules.size - MODULES.length);
    const slots = [
      { x: -1.65, z: -1.25 },
      { x: 1.85, z: -1.25 },
      { x: 3.25, z: 1.05 },
      { x: -3.35, z: -1.25 },
    ];
    const slot = slots[nextIndex % slots.length];
    const def = {
      id,
      title: type === "storage" ? "储能资产" : type === "generation" ? "发电资产" : type === "factory" ? "厂房资产" : "负荷资产",
      device: "未绑定遥测",
      metric: "待接入",
      note: "已接入主母线",
      x: slot.x + Math.floor(nextIndex / slots.length) * .35,
      z: slot.z,
      kind: type === "datacenter" ? "load" : type,
    };
    const module = makeModule(def);
    modules.set(id, module);
    scene.add(module);
    selectedId = id;
    rebuildTopologyWire(topologyWire, modules);
    syncRoutesToModules();
  }

  function deleteSelected() {
    const module = modules.get(selectedId);
    if (!module || ["grid", "solar", "storage", "load"].includes(selectedId)) return;
    scene.remove(module);
    modules.delete(selectedId);
    selectedId = "load";
    rebuildTopologyWire(topologyWire, modules);
    syncRoutesToModules();
  }

  function reset() {
    MODULES.forEach((def) => {
      const module = modules.get(def.id);
      if (module) module.position.set(def.x, 0, def.z);
    });
    rebuildTopologyWire(topologyWire, modules);
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
