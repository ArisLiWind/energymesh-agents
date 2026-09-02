# AgentTeams 调试环境快速搭建

> 面向复赛的 **真实多 Agent 运行环境** 调试指南。
> 解决 Codespace 休眠、端口转发断开、Worker 掉线等常见问题。

---

## 前提条件

1. **GitHub Codespace** 已创建（推荐 2-core, 8GB RAM）
2. **GitHub CLI (`gh`)** 已安装并登录
3. **Docker** 在 Codespace 内可用（GitHub Codespaces 默认自带）

---

## 1. 克隆仓库（别人要做的第一步）

```bash
git clone https://github.com/ArisLiWind/energymesh-agents.git
cd energymesh-agents
```

---

## 2. 启动 Codespace 并连接端口

在你的 **本地电脑**（Mac/Windows/Linux）上运行：

```bash
# 一键连接 Codespace + 端口转发
bash scripts/connect_codespace.sh
```

这个脚本会：
- 自动检测你的 Codespace（如果没在运行会唤醒它）
- 启动 Docker 容器（如果之前休眠停了）
- 把 Codespace 的端口转发到本地：
  - `127.0.0.1:18080` → Matrix Homeserver
  - `127.0.0.1:18088` → Element Web UI

**成功标志**：
```
✓ Matrix homeserver: http://127.0.0.1:18080
✓ Element web:       http://127.0.0.1:18088
```

---

## 3. 在 Codespace 内启动保活服务

Codespace **30 分钟无操作会自动休眠**，连带 Docker 容器全部停止。

在**本地**运行以下命令，在 Codespace 内启动后台保活：

```bash
# 在本地执行，远程启动 Codespace 上的保活进程
gh codespace ssh -c $(gh codespace list --json name --jq '.[0].name') -- \
  "bash scripts/start_codespace_keepalive.sh"
```

或者先 SSH 进 Codespace，再手动执行：

```bash
gh codespace ssh
# 进入 codespace 后
bash scripts/start_codespace_keepalive.sh
```

保活脚本会：
- 每 5 分钟 ping 一次 Matrix/Element/Manager/Worker，保持服务温热
- 每 5 分钟触碰工作区文件，让 GitHub 检测到活动
- 确保所有容器都设置了 `unless-stopped` 自动重启策略

> ⚠️ **注意**：GitHub Codespace 最大空闲超时为 **4 小时**。如果需要 24h 不间断运行，请使用自有服务器或云主机。

---

## 4. 本地启动 EnergyMesh 后端

```bash
# 复制环境模板
cp .env.example .env.agentteams.local

# 编辑 .env.agentteams.local，填入：
# - AGENTTEAMS_LLM_API_KEY=你的 DeepSeek API Key
# - AGENTTEAMS_MATRIX_ACCESS_TOKEN=Matrix 管理员 Token（见下方获取方法）
# - AGENTTEAMS_TEAM_ROOM_ID=Team Room ID

# 安装依赖并启动
pip install -r requirements.txt
python -m energymesh.api
```

或者运行：
```bash
bash scripts/start_agentteams_demo.sh
```

---

## 5. 获取 Matrix Access Token

在浏览器打开 http://127.0.0.1:18088 进入 Element，用管理员账号登录后：

```bash
curl -XPOST -d '{"type":"m.login.password", "user":"admin", "password":"20260903"}' \
  http://127.0.0.1:18080/_matrix/client/r0/login | jq -r '.access_token'
```

把拿到的 token 填进 `.env.agentteams.local` 的 `AGENTTEAMS_MATRIX_ACCESS_TOKEN`。

---

## 6. 常见故障排查

### Q: "Connectivity to the server has been lost"
**原因**：Codespace 休眠了，或者端口转发断了。  
**解决**：重新跑 `bash scripts/connect_codespace.sh`。

### Q: Worker 状态显示 Failed
**原因**：API Key 过期、网络不通、或 LLM 调用失败。  
**解决**：
```bash
# 查看 Worker 日志
docker logs agentteams-worker-energy-dispatcher

# 重启所有 Worker
docker restart $(docker ps -aqf name=agentteams-worker)
```

### Q: Element 页面白屏或登录不了
**原因**：homeserver URL 配置不对。Element 里的默认配置是 `http://127.0.0.1:18080`。  
**解决**：确保端口转发在运行，直接访问 http://127.0.0.1:18088。

---

## 7. 目录结构

```
scripts/
├── connect_codespace.sh          # 本地用：连接 Codespace + 端口转发
├── start_codespace_keepalive.sh  # Codespace 内：启动保活后台
├── codespace_keepalive.sh        # 保活脚本本体（由上面调用）
├── start_agentteams_demo.sh      # 一键启动本地后端
└── agentteams_runtime_check.sh   # 检查 AgentTeams 各组件状态
```

---

## 8. 端口映射速查

| 服务 | Codespace 内部 | 映射到本地（Mac） | 说明 |
|------|---------------|-------------------|------|
| Matrix Homeserver | `127.0.0.1:18080` | `127.0.0.1:18080` | Tuwunel (Conduwuit fork) |
| Element Web | `127.0.0.1:18088` | `127.0.0.1:18088` | 聊天界面 |
| AgentTeams Manager | `127.0.0.1:18888` | （不转发） | 管理后台 |
| EnergyMesh API | `127.0.0.1:8000` | `127.0.0.1:8000` | FastAPI 本地 |
