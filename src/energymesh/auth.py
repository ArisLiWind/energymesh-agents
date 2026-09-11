"""Optional shared-password authentication for the EnergyMesh API and console.

The service is designed for a single public entry point. When
``ENERGYMESH_AUTH_PASSWORD`` is configured, every request except the health
probe and the login page must present a valid session cookie. Without the
variable the service keeps its historical open behaviour, which keeps local
development and the pytest suite unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

SESSION_COOKIE = "ems_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600

_OPEN_PATHS = {"/api/health", "/login", "/logout", "/favicon.ico"}

_LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EnergyMesh 登录</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6f9; display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(15,34,58,.08);
          padding: 40px 36px; width: 340px; }
  h1 { font-size: 20px; margin: 0 0 6px; color: #12263f; }
  p { margin: 0 0 22px; color: #64748b; font-size: 13px; }
  input[type=password] { width: 100%; box-sizing: border-box; padding: 11px 12px;
          border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; margin-bottom: 14px; }
  input[type=password]:focus { outline: none; border-color: #2563eb; }
  button { width: 100%; padding: 11px 0; border: none; border-radius: 8px;
           background: #2563eb; color: #fff; font-size: 14px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  .error { color: #dc2626; font-size: 13px; margin: 0 0 14px; }
</style>
</head>
<body>
  <div class="card">
    <h1>EnergyMesh 能源调度平台</h1>
    <p>请输入访问密码登录运营控制台</p>
    {error}
    <form method="post" action="/login">
      <input type="password" name="password" placeholder="访问密码" autofocus required>
      <button type="submit">登 录</button>
    </form>
  </div>
</body>
</html>
"""


@dataclass(frozen=True)
class AuthConfig:
    """Shared-password configuration sourced from environment variables."""

    password: str | None
    secret: str

    @classmethod
    def from_env(cls) -> "AuthConfig":
        password = os.getenv("ENERGYMESH_AUTH_PASSWORD", "").strip() or None
        secret = (
            os.getenv("ENERGYMESH_AUTH_SECRET", "").strip()
            or password
            or secrets.token_hex(32)
        )
        return cls(password=password, secret=secret)

    @property
    def enabled(self) -> bool:
        return self.password is not None


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(secret: str) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{expires}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(secret, payload)}"


def verify_session_token(secret: str, token: str | None) -> bool:
    if not token:
        return False
    try:
        payload, signature = token.rsplit(".", 1)
        expires_text, _nonce = payload.split(".", 1)
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            return False
        return int(expires_text) > time.time()
    except (ValueError, TypeError):
        return False


def install_auth(app: FastAPI, config: AuthConfig) -> None:
    """Attach the login routes and the gate middleware to ``app``."""

    @app.get("/login", include_in_schema=False)
    def login_page(error: str = "") -> HTMLResponse:
        error_block = '<p class="error">密码不正确，请重试。</p>' if error else ""
        return HTMLResponse(_LOGIN_PAGE.replace("{error}", error_block))

    @app.post("/login", include_in_schema=False)
    async def login_submit(request: Request) -> RedirectResponse:
        form = await request.form()
        password = str(form.get("password", ""))
        if config.password is not None and hmac.compare_digest(password, config.password):
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE,
                create_session_token(config.secret),
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                samesite="lax",
            )
            return response
        return RedirectResponse("/login?error=1", status_code=303)

    @app.get("/logout", include_in_schema=False)
    def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.middleware("http")
    async def auth_gate(request: Request, call_next: object) -> object:
        path = request.url.path
        if path in _OPEN_PATHS or not config.enabled:
            return await call_next(request)  # type: ignore[operator]
        token = request.cookies.get(SESSION_COOKIE)
        if verify_session_token(config.secret, token):
            return await call_next(request)  # type: ignore[operator]
        if path.startswith("/api/") or path.startswith("/mcp/"):
            return JSONResponse({"detail": "not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=302)
