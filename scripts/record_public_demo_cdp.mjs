import { mkdir, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outDir = "/tmp/energymesh_real_demo_frames";
const csvPath = "/Users/zhuanz1mima0000/Desktop/2025-07-a.csv";

function sh(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts });
    let stdout = "";
    let stderr = "";
    p.stdout.on("data", (d) => (stdout += d));
    p.stderr.on("data", (d) => (stderr += d));
    p.on("exit", (code) => (code === 0 ? resolve({ stdout, stderr }) : reject(new Error(stderr || stdout))));
  });
}

async function json(url) {
  const r = await fetch(url);
  return r.json();
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    });
  }
  ready() {
    return new Promise((resolve) => this.ws.addEventListener("open", resolve, { once: true }));
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
}

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const tabs = await json("http://127.0.0.1:9222/json");
      const page = tabs.find((t) => t.type === "page");
      if (page) {
        const cdp = new CDP(page.webSocketDebuggerUrl);
        await cdp.ready();
        await cdp.send("Page.enable");
        await cdp.send("Runtime.enable");
        await cdp.send("DOM.enable");
        await cdp.send("Emulation.setDeviceMetricsOverride", {
          width: 1440,
          height: 900,
          deviceScaleFactor: 1,
          mobile: false,
        });
        return cdp;
      }
    } catch {}
    await delay(500);
  }
  throw new Error("Chrome DevTools did not start");
}

async function shot(cdp, name) {
  await delay(900);
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(`${outDir}/${name}.png`, Buffer.from(data, "base64"));
}

async function evalJs(cdp, expression) {
  return cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
}

async function main() {
  await mkdir(outDir, { recursive: true });
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--remote-debugging-port=9222",
    "--disable-gpu",
    "--no-first-run",
    "--window-size=1440,900",
    "about:blank",
  ], { stdio: "ignore" });

  try {
    const cdp = await connect();
    let n = 1;
    await cdp.send("Page.navigate", { url: "https://energymesh.gensphereai.xyz/" });
    await cdp.send("Page.loadEventFired").catch(() => {});
    await delay(3500);
    await shot(cdp, String(n++).padStart(3, "0"));

    await evalJs(cdp, `document.querySelector('#nav-connect')?.click()`);
    await shot(cdp, String(n++).padStart(3, "0"));

    const { root } = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
    const input = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector: 'input[type="file"]' });
    if (input.nodeId) {
      await cdp.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [csvPath] });
      await delay(2500);
      await shot(cdp, String(n++).padStart(3, "0"));
    }

    await evalJs(cdp, `document.querySelector('button[aria-label="Close"], button')?.click()`);
    await delay(500);
    await evalJs(cdp, `document.querySelector('#nav-workspace')?.click()`);
    for (let i = 0; i < 5; i++) {
      await evalJs(cdp, `document.querySelector('#replay-slider')?.stepUp?.(4); document.querySelector('#replay-slider')?.dispatchEvent(new Event('input',{bubbles:true}))`);
      await shot(cdp, String(n++).padStart(3, "0"));
    }

    await evalJs(cdp, `document.querySelector('#demo-production-change')?.click()`);
    await shot(cdp, String(n++).padStart(3, "0"));
    await evalJs(cdp, `document.querySelector('#demo-approve-v3')?.click()`);
    await shot(cdp, String(n++).padStart(3, "0"));
    await evalJs(cdp, `document.querySelector('#demo-execute-v3')?.click()`);
    await shot(cdp, String(n++).padStart(3, "0"));

    await evalJs(cdp, `document.querySelector('#ai-chat-input')?.focus(); document.querySelector('#ai-chat-input').value='请根据生产计划提前和SOC不低于30%的约束，让多Agent完成重新调度、审计、审批和EMS回读。'; document.querySelector('#ai-chat-input').dispatchEvent(new Event('input',{bubbles:true}));`);
    await shot(cdp, String(n++).padStart(3, "0"));
    await evalJs(cdp, `document.querySelector('#ai-chat-form button, button[type=submit]')?.click()`);
    await delay(2500);
    await shot(cdp, String(n++).padStart(3, "0"));

    await cdp.send("Page.navigate", { url: "https://agents.gensphereai.xyz/#/room/local+m1789848577121.0" });
    await delay(6000);
    for (let i = 0; i < 5; i++) {
      await shot(cdp, String(n++).padStart(3, "0"));
      await evalJs(cdp, `window.scrollBy(0, 260)`);
    }

    await sh("ffmpeg", [
      "-y",
      "-framerate", "1",
      "-i", `${outDir}/%03d.png`,
      "-vf", "scale=1440:900,format=yuv420p",
      "-c:v", "libx264",
      "-pix_fmt", "yuv420p",
      "/Users/zhuanz1mima0000/Desktop/energymesh-agentteams-real-demo.mp4",
    ]);
  } finally {
    chrome.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
