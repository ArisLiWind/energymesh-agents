#!/usr/bin/env python3
"""Local-only form for saving AgentTeams LLM settings without echoing secrets."""

from __future__ import annotations

import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env.agentteams.local"
HOST = "127.0.0.1"
PORT = int(os.environ.get("ENERGYMESH_SECRET_FORM_PORT", "8765"))


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EnergyMesh AgentTeams Key</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f8fb; color: #172033; }
    main { width: min(560px, calc(100vw - 32px)); background: #fff; border: 1px solid #dbe4ef; border-radius: 10px; padding: 26px; box-shadow: 0 18px 60px rgba(32, 45, 70, .12); }
    h1 { margin: 0 0 8px; font-size: 22px; }
    p { margin: 0 0 20px; color: #66758d; line-height: 1.55; }
    label { display: block; margin: 14px 0 6px; font-weight: 650; font-size: 13px; color: #33415c; }
    input, select { width: 100%; box-sizing: border-box; height: 42px; border: 1px solid #cdd8e6; border-radius: 8px; padding: 0 12px; font-size: 14px; background: #fff; }
    button { width: 100%; margin-top: 20px; height: 44px; border: 0; border-radius: 8px; background: #0f766e; color: white; font-weight: 700; font-size: 15px; cursor: pointer; }
    small { display: block; margin-top: 14px; color: #8a98ad; line-height: 1.45; }
  </style>
</head>
<body>
<main>
  <h1>AgentTeams LLM 配置</h1>
  <p>这个页面只监听 127.0.0.1。提交后会保存到本机仓库的 .env.agentteams.local，不会显示密钥明文。</p>
  <form method="post" action="/save" autocomplete="off">
    <label for="provider">模型服务</label>
    <select id="provider" name="provider">
      <option value="openai-compat">DeepSeek / OpenAI-compatible</option>
      <option value="qwen">通义千问 / DashScope</option>
    </select>
    <label for="base_url">Base URL</label>
    <input id="base_url" name="base_url" value="https://api.deepseek.com/v1" />
    <label for="model">默认模型</label>
    <input id="model" name="model" value="deepseek-chat" />
    <label for="key">API Key</label>
    <input id="key" name="key" type="password" required autofocus />
    <button type="submit">保存并关闭</button>
    <small>DeepSeek 使用 OpenAI-compatible 协议。通义兼容模式可填 DashScope compatible-mode URL。</small>
  </form>
</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/":
            self.send_error(404)
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        provider = fields.get("provider", ["openai-compat"])[0].strip() or "openai-compat"
        base_url = fields.get("base_url", [""])[0].strip()
        model = fields.get("model", [""])[0].strip() or "gpt-4o-mini"
        key = fields.get("key", [""])[0].strip()
        if not key:
            self.send_error(400, "missing API key")
            return
        lines = [
            "# Local AgentTeams settings. Do not commit.",
            f"AGENTTEAMS_LLM_PROVIDER={provider}",
            f"AGENTTEAMS_OPENAI_BASE_URL={base_url}",
            f"AGENTTEAMS_DEFAULT_MODEL={model}",
            f"AGENTTEAMS_LLM_API_KEY={key}",
            "AGENTTEAMS_NON_INTERACTIVE=1",
            "AGENTTEAMS_DASHBOARD=0",
            "AGENTTEAMS_MANAGER_RUNTIME=qwenpaw",
        ]
        TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(TARGET, 0o600)
        msg = f"已保存到 {html.escape(str(TARGET))}。现在可以回到 Codex 继续安装 AgentTeams。"
        body = f"<!doctype html><meta charset='utf-8'><body style='font-family:-apple-system;padding:32px'><h2>保存成功</h2><p>{msg}</p></body>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
