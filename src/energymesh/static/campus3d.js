import * as THREE from "/static/vendor/three.module.min.js";

const GRID_STEP = 2;
const GRID_LIMIT = 22;
const MODULE_TYPES = {
  factory: { title: "负载", metric: "25 MW", note: "日用电量 100 MWh", category: "用电端" },
  solar: { title: "光伏", metric: "10 MW", note: "日发电量 42 MWh", category: "发电端" },
  storage: { title: "储能", metric: "SOC 20%", note: "当前功率 0 MW", category: "储能端" },
  grid: { title: "电网", metric: "15 MW", note: "日购电量 100 MWh", category: "外部输入" },
  charge: { title: "充电负载", metric: "2 MW", note: "日用电量 8 MWh", category: "用电端" },
  compute: { title: "数据负载", metric: "5 MW", note: "日用电量 28 MWh", category: "用电端" },
  datacenter: { title: "数据中心", metric: "6 MW", note: "新增用电端", category: "用电端" },
  generation: { title: "发电机", metric: "20 MW", note: "日发电量 58 MWh", category: "发电端" },
};

const materials = {
  ground: new THREE.MeshStandardMaterial({ color: 0xdcecf2, roughness: 1 }),
  road: new THREE.MeshStandardMaterial({ color: 0xb9ccd8, roughness: 1 }),
  pad: new THREE.MeshStandardMaterial({ color: 0xe7f0f6, roughness: 0.85 }),
  white: new THREE.MeshStandardMaterial({ color: 0xf4f8fb, roughness: 0.7 }),
  side: new THREE.MeshStandardMaterial({ color: 0xb9c9d5, roughness: 0.82 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x26323f, roughness: 0.68 }),
  glass: new THREE.MeshStandardMaterial({ color: 0x2fabc7, roughness: 0.24, metalness: 0.08 }),
  solar: new THREE.MeshStandardMaterial({ color: 0x24536f, roughness: 0.36 }),
  tree: new THREE.MeshStandardMaterial({ color: 0x22b59c, roughness: 0.8 }),
  pipe: new THREE.MeshStandardMaterial({
    color: 0x6fe7d1,
    emissive: 0x22bba4,
    emissiveIntensity: 0.42,
    roughness: 0.42,
  }),
  selected: new THREE.MeshStandardMaterial({
    color: 0x9ff3e5,
    emissive: 0x28d2b9,
    emissiveIntensity: 0.35,
    transparent: true,
    opacity: 0.42,
  }),
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

function box(group, size, position, material = materials.white) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function cylinder(group, radius, height, position, material = materials.side, segments = 24) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, segments), material);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function cone(group, radius, height, position) {
  const mesh = new THREE.Mesh(new THREE.ConeGeometry(radius, height, 6), materials.tree);
  mesh.position.set(...position);
  mesh.castShadow = true;
  group.add(mesh);
  return mesh;
}

function pad(group) {
  box(group, [3.7, 0.16, 3.7], [0, 0.08, 0], materials.pad);
}

function addWindows(group, count, x, y, zStart, spacing) {
  for (let index = 0; index < count; index += 1) {
    box(group, [0.08, 0.34, 0.34], [x, y, zStart + index * spacing], materials.glass);
  }
}

function buildModule(type) {
  const group = new THREE.Group();
  pad(group);
  if (type === "factory") {
    box(group, [2.9, 1.0, 1.8], [-0.25, 0.66, 0], materials.white);
    box(group, [3.25, 0.32, 2.1], [-0.25, 1.3, 0], materials.dark);
    for (let index = 0; index < 3; index += 1) {
      cylinder(group, 0.13, 1.35, [-1.1 + index * 0.55, 1.55, -0.55], materials.side, 16);
    }
    addWindows(group, 4, 1.25, 0.74, -0.65, 0.42);
  } else if (type === "solar") {
    for (let row = 0; row < 3; row += 1) {
      for (let col = 0; col < 3; col += 1) {
        const panel = box(group, [0.72, 0.08, 0.52], [-0.8 + col * 0.8, 0.34, -0.6 + row * 0.6], materials.solar);
        panel.rotation.x = -0.26;
      }
    }
  } else if (type === "storage") {
    for (let index = 0; index < 3; index += 1) {
      box(group, [0.58, 1.32, 1.05], [-0.75 + index * 0.75, 0.74, 0], index % 2 ? materials.side : materials.white);
      box(group, [0.38, 0.08, 0.5], [-0.75 + index * 0.75, 1.08, 0.28], materials.glass);
    }
  } else if (type === "grid") {
    cylinder(group, 0.2, 0.16, [0, 0.28, 0], materials.pipe);
    const lineMaterial = new THREE.LineBasicMaterial({ color: 0x8092a0 });
    const points = [
      [-0.7, 0.18, -0.6], [0, 2.6, 0], [0.7, 0.18, -0.6],
      [-0.55, 1.1, -0.45], [0.55, 1.1, -0.45],
      [-0.35, 1.72, -0.25], [0.35, 1.72, -0.25],
    ].map((point) => new THREE.Vector3(...point));
    group.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points), lineMaterial));
  } else if (type === "charge") {
    for (let index = 0; index < 3; index += 1) {
      box(group, [0.34, 1.0, 0.38], [-0.75 + index * 0.75, 0.58, 0.1], materials.white);
      box(group, [0.22, 0.25, 0.04], [-0.75 + index * 0.75, 0.76, -0.12], materials.glass);
    }
    box(group, [2.4, 0.16, 0.7], [0, 0.24, 0.9], materials.side);
  } else if (type === "compute" || type === "datacenter") {
    const height = type === "datacenter" ? 2.6 : 1.45;
    box(group, [2.2, height, 1.7], [0, 0.16 + height / 2, 0], materials.white);
    box(group, [1.6, 0.18, 1.25], [0, height + 0.34, 0], materials.side);
    addWindows(group, 5, -1.13, 0.75, -0.68, 0.34);
    for (let index = 0; index < 2; index += 1) {
      cylinder(group, 0.22, 0.16, [-0.35 + index * 0.7, height + 0.52, 0], materials.dark, 20);
    }
  } else if (type === "generation") {
    box(group, [2.2, 0.8, 1.4], [0, 0.5, 0], materials.white);
    cylinder(group, 0.34, 1.4, [-0.55, 1.08, -0.32], materials.side, 28);
    cylinder(group, 0.24, 1.9, [0.55, 1.35, -0.28], materials.side, 28);
  }
  for (let index = 0; index < 3; index += 1) {
    cone(group, 0.15, 0.65, [-1.25 + index * 1.25, 0.48, 1.55]);
  }
  return group;
}

function snap(value) {
  return Math.round(value / GRID_STEP) * GRID_STEP;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function makePipeSegment(from, to) {
  const length = Math.hypot(to.x - from.x, to.z - from.z);
  const horizontal = Math.abs(to.x - from.x) > Math.abs(to.z - from.z);
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(horizontal ? length : 0.16, 0.08, horizontal ? 0.16 : length),
    materials.pipe,
  );
  mesh.position.set((from.x + to.x) / 2, 0.18, (from.z + to.z) / 2);
  return mesh;
}

export function createCampus3D(canvas, onLabels) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0xddebf3);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xddebf3, 42, 86);
  const camera = new THREE.OrthographicCamera(-10, 10, 7, -7, 0.1, 120);
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  let azimuth = -0.72;
  let elevation = 0.82;
  let zoom = 1.02;
  let orbiting = false;
  let draggingModule = false;
  let selectedId = null;
  let pointer = [0, 0];
  let idCounter = 1;
  let flowMultiplier = 1;

  const moduleRoot = new THREE.Group();
  const pipeRoot = new THREE.Group();
  const poolRoot = new THREE.Group();
  const selectable = [];
  const modules = initialModules.map((item) => ({ ...item }));
  scene.add(pipeRoot, poolRoot, moduleRoot);

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(90, 90),
    materials.ground,
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const gridHelper = new THREE.GridHelper(70, 70, 0x9fb6c5, 0xc5d6df);
  gridHelper.position.y = 0.02;
  scene.add(gridHelper);

  const roadRoot = new THREE.Group();
  for (let value = -22; value <= 22; value += 4) {
    box(roadRoot, [0.52, 0.035, 48], [value, 0.045, 0], materials.road);
    box(roadRoot, [48, 0.035, 0.52], [0, 0.046, value], materials.road);
  }
  scene.add(roadRoot);

  const skyline = new THREE.Group();
  for (let index = 0; index < 22; index += 1) {
    const height = 1.2 + (index % 5) * 0.65;
    const width = 1.1 + (index % 3) * 0.35;
    box(skyline, [width, height, width], [-30 + index * 2.9, height / 2, -31], materials.side);
  }
  skyline.children.forEach((mesh) => {
    mesh.material = new THREE.MeshStandardMaterial({
      color: 0xe0edf5,
      roughness: 1,
      transparent: true,
      opacity: 0.48,
    });
  });
  scene.add(skyline);

  scene.add(new THREE.HemisphereLight(0xf8fbff, 0x99b4c7, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 3.1);
  sun.position.set(-9, 16, 9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -24;
  sun.shadow.camera.right = 24;
  sun.shadow.camera.top = 24;
  sun.shadow.camera.bottom = -24;
  scene.add(sun);

  const poolBase = new THREE.Mesh(new THREE.CylinderGeometry(1.05, 1.05, 0.14, 42), materials.pipe);
  poolBase.position.set(0, 0.16, 0);
  poolRoot.add(poolBase);
  const poolRing = new THREE.Mesh(new THREE.TorusGeometry(1.16, 0.035, 8, 48), materials.pipe);
  poolRing.rotation.x = Math.PI / 2;
  poolRing.position.set(0, 0.28, 0);
  poolRoot.add(poolRing);

  function positionCamera() {
    const radius = 31;
    camera.position.set(
      Math.sin(azimuth) * Math.cos(elevation) * radius,
      Math.sin(elevation) * radius,
      Math.cos(azimuth) * Math.cos(elevation) * radius,
    );
    camera.zoom = zoom;
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }

  function rebuildModules() {
    moduleRoot.clear();
    selectable.length = 0;
    modules.forEach((module) => {
      const group = buildModule(module.type);
      group.scale.setScalar(1.18);
      group.position.set(module.x, 0, module.z);
      group.userData = { moduleId: module.id };
      group.traverse((child) => {
        child.userData.moduleId = module.id;
        if (child.isMesh) selectable.push(child);
      });
      const selection = new THREE.Mesh(new THREE.BoxGeometry(4.05, 0.05, 4.05), materials.selected);
      selection.position.set(0, 0.19, 0);
      selection.visible = module.id === selectedId;
      selection.userData.moduleId = module.id;
      group.add(selection);
      moduleRoot.add(group);
    });
    rebuildPipes();
  }

  function rebuildPipes() {
    pipeRoot.clear();
    const pool = { x: 0, z: 0 };
    modules.forEach((module) => {
      const corner = { x: module.x, z: 0 };
      pipeRoot.add(makePipeSegment(corner, module));
      pipeRoot.add(makePipeSegment(pool, corner));
    });
  }

  function moduleAtPointer(event) {
    const rect = canvas.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const hit = raycaster.intersectObjects(selectable, false)[0];
    return hit ? modules.find((module) => module.id === hit.object.userData.moduleId) : null;
  }

  function groundPoint(event) {
    const rect = canvas.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const point = new THREE.Vector3();
    raycaster.ray.intersectPlane(groundPlane, point);
    return {
      x: clamp(snap(point.x), -GRID_LIMIT, GRID_LIMIT),
      z: clamp(snap(point.z), -GRID_LIMIT, GRID_LIMIT),
    };
  }

  function select(id) {
    selectedId = id;
    moduleRoot.children.forEach((group) => {
      const selection = group.children[group.children.length - 1];
      selection.visible = group.userData.moduleId === selectedId;
    });
  }

  function resize() {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false);
    const aspect = width / height;
    camera.left = -9 * aspect;
    camera.right = 9 * aspect;
    camera.top = 9;
    camera.bottom = -9;
    camera.updateProjectionMatrix();
  }

  function updateLabels() {
    if (!onLabels) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const labels = {};
    modules.forEach((module) => {
      const type = MODULE_TYPES[module.type] || MODULE_TYPES.factory;
      const anchor = new THREE.Vector3(module.x, 2.3, module.z).project(camera);
      const x = (anchor.x * 0.5 + 0.5) * width;
      const y = (-anchor.y * 0.5 + 0.5) * height;
      labels[module.id] = {
        x: clamp(x, 68, width - 68),
        y: clamp(y, 42, height - 26),
        visible: module.id === selectedId && anchor.z > -1 && anchor.z < 1,
        title: `${type.title} · ${type.category}`,
        metric: type.metric,
        note: type.note,
      };
    });
    onLabels(labels);
  }

  canvas.addEventListener("pointerdown", (event) => {
    const module = moduleAtPointer(event);
    pointer = [event.clientX, event.clientY];
    canvas.setPointerCapture(event.pointerId);
    if (module) {
      select(module.id);
      draggingModule = true;
      return;
    }
    orbiting = true;
  });

  canvas.addEventListener("pointermove", (event) => {
    if (draggingModule && selectedId) {
      const module = modules.find((item) => item.id === selectedId);
      if (!module) return;
      const point = groundPoint(event);
      module.x = point.x;
      module.z = point.z;
      const group = moduleRoot.children.find((item) => item.userData.moduleId === selectedId);
      if (group) group.position.set(module.x, 0, module.z);
      rebuildPipes();
      return;
    }
    if (!orbiting) return;
    azimuth -= (event.clientX - pointer[0]) * 0.005;
    elevation = clamp(elevation + (event.clientY - pointer[1]) * 0.003, 0.48, 1.18);
    pointer = [event.clientX, event.clientY];
    positionCamera();
  });

  canvas.addEventListener("pointerup", () => {
    draggingModule = false;
    orbiting = false;
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom = clamp(zoom - event.deltaY * 0.0007, 0.62, 1.45);
    positionCamera();
  }, { passive: false });

  let frame = 0;
  function render(time) {
    materials.pipe.emissiveIntensity = 0.28 + flowMultiplier + Math.sin(time * 0.004) * 0.12;
    poolRing.rotation.z += 0.01 * flowMultiplier;
    updateLabels();
    renderer.render(scene, camera);
    frame = requestAnimationFrame(render);
  }

  positionCamera();
  resize();
  rebuildModules();
  select("factory");
  render(0);
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);

  return {
    addModule(type = "datacenter") {
      const template = MODULE_TYPES[type] ? type : "datacenter";
      const id = `${template}-${idCounter}`;
      idCounter += 1;
      modules.push({
        id,
        type: template,
        x: clamp(snap(-2 + idCounter * 2), -GRID_LIMIT, GRID_LIMIT),
        z: clamp(snap(2 + idCounter), -GRID_LIMIT, GRID_LIMIT),
      });
      rebuildModules();
      select(id);
    },
    deleteSelected() {
      if (!selectedId || modules.length <= 1) return;
      const index = modules.findIndex((module) => module.id === selectedId);
      if (index >= 0) modules.splice(index, 1);
      selectedId = modules[0]?.id || null;
      rebuildModules();
      if (selectedId) select(selectedId);
    },
    applyEnergyState(payload = {}) {
      flowMultiplier = payload.optimized ? 0.5 : 0.22;
      MODULE_TYPES.grid.metric = payload.optimized ? "8 MW" : "15 MW";
      MODULE_TYPES.grid.note = payload.optimized ? "日购电量 70 MWh" : "日购电量 100 MWh";
      MODULE_TYPES.storage.metric = payload.storage || (payload.optimized ? "SOC 79%" : "SOC 20%");
      MODULE_TYPES.storage.note = payload.optimized ? "充放电调峰中" : "当前功率 0 MW";
      MODULE_TYPES.factory.metric = payload.load || "25 MW";
      MODULE_TYPES.factory.note = payload.optimized ? "总用电量下降 15%" : "日用电量 100 MWh";
      MODULE_TYPES.compute.note = payload.optimized ? "安全接入完成" : "关键负载";
      rebuildModules();
      if (selectedId) select(selectedId);
    },
    reset() {
      azimuth = -0.72;
      elevation = 0.82;
      zoom = 1.02;
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
