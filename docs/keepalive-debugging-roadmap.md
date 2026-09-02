# EnergyMesh 多 Worker 服务保活与超时配置调试路线图

> 版本: v1.0 | 日期: 2026-09-02 | 状态: 草案待确认

---

## 1. 背景与目标

### 1.1 当前状态

EnergyMesh 已完成 GitHub 外部依赖解除，代码已推送至远程仓库。现阶段核心挑战是：

- **多 Worker 协同调试期间服务频繁离线**，影响 AgentTeams 团队协作调试体验
- 现有的 `codespace_keepalive.sh` 仅针对 GitHub Codespaces 环境，本地调试缺乏保活能力
- 超时配置分散在 6 个模块中，缺乏统一管理，部分默认值在 LLM 调用高峰时段偏短

### 1.2 目标

| 目标 | 描述 |
|------|------|
| 本地保活 | 提供独立于 Codespaces 的本地 keep-alive 脚本，覆盖所有关键服务端口 |
| 超时配置优化 | 审计并统一调整 6 个模块的超时参数，消除因超时过短导致的任务失败 |
| 自动恢复 | 配置 Docker 容器自动重启 + 进程级守护，确保调试期间服务不中断 |
| 可验证性 | 提供分阶段检查清单，每步可独立验证 |

---

## 2. 系统架构概览 — 超时与心跳路径

```
┌─────────────────────────────────────────────────────────┐
│                    EnergyMesh FastAPI (:8000)            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │Perception│  │ Dispatch │  │  Audit   │  ... Workers  │
│  │ Worker   │  │ Worker   │  │  Worker  │              │
│  │timeout=15│  │timeout=30│  │timeout=20│              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│  ┌────▼──────────────▼──────────────▼─────┐              │
│  │         WorkerPool (ThreadPool)         │              │
│  │  default_timeout=30  max_workers=8     │              │
│  └────────────────────┬───────────────────┘              │
│                       │                                   │
│  ┌────────────────────▼───────────────────┐              │
│  │         Skill Registry                  │              │
│  │  各 Skill 独立 timeout (10-30s)         │              │
│  └────────────────────┬───────────────────┘              │
│                       │                                   │
│  ┌────────────────────▼───────────────────┐              │
│  │      Model Gateway (OpenAI Client)      │              │
│  │  timeout=30  (DeepSeek API)             │              │
│  └─────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              AgentTeams Runtime (Matrix)                  │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │agentteams-controller│ │agentteams-manager │            │
│  │  :8080/:8088      │  │  :18080/:18088   │             │
│  └────────┬─────────┘  └────────┬─────────┘             │
│           │                      │                        │
│  ┌────────▼──────────────────────▼─────────┐             │
│  │     Matrix Homeserver (:18080)           │             │
│  │     Element Web UI (:18088)              │             │
│  │     Poll timeout: 90s (env configurable) │             │
│  └──────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 超时配置完整审计

### 3.1 当前超时参数全景

| 模块 | 文件 | 参数 | 当前值 | 建议值 | 理由 |
|------|------|------|--------|--------|------|
| **OpenAI Client** | `model_gateway.py:145-149` | `timeout` | 30s | **60s** | DeepSeek 高峰时段响应可能超过 30s；仅改 API 调用超时 |
| **WorkerPool** | `worker_pool.py:68` | `default_timeout` | 30.0s | **45.0s** | 作为兜底值应略宽松 |
| **WorkerTask** | `worker_pool.py:41` | `deadline_seconds` | 30.0s | **45.0s** | 与 default_timeout 对齐 |
| **Perception Skill** | `orchestrator_v2.py:244` | `timeout_seconds` | 15.0s | **20.0s** | 核验场景含 LLM 调用时 15s 偏紧 |
| **Dispatch Skill** | `orchestrator_v2.py:268` | `timeout_seconds` | 30.0s | **45.0s** | 策略生成涉及求解器 + LLM，是最大瓶颈 |
| **Audit Skill** | `orchestrator_v2.py:291` | `timeout_seconds` | 20.0s | **30.0s** | 审核含独立复算，到达 20s 频发 |
| **Execution Skill** | `orchestrator_v2.py:316` | `timeout_seconds` | 20.0s | **25.0s** | 模拟执行较稳定，小幅放宽 |
| **Approval Skill** | `orchestrator_v2.py:337` | `timeout_seconds` | 10.0s | **15.0s** | 审批逻辑简单，但含 LLM 判断 |
| **AgentWorker** | `agent_worker.py:57` | `timeout_seconds` | 30.0s | **45.0s** | 与 WorkerPool 对齐 |
| **AgentWorker** | `agent_worker.py:56` | `max_retries` | 2 | **2** (不变) | 当前合理 |
| **Lifecycle wait** | `orchestrator_v2.py:102` | `timeout` | 30.0s | **60.0s** | 等待阶段转换应更宽松 |
| **Matrix poll** | `agentteams_runtime.py:718` | env `AGENTTEAMS_MATRIX_POLL_TIMEOUT` | 90s | **120s** | 避免长轮询过早断开 |
| **Matrix sync** | `agentteams_runtime.py:724` | `timeout` query param | 30000ms | **60000ms** | 与 poll timeout 对齐 |
| **Matrix message send** | `agentteams_runtime.py:699` | `timeout` | 60s | **90s** | Worker 消息可达较大 payload |

### 3.2 超时关系链

```
API 请求 → Model Gateway (30s→60s)
         → WorkerPool.dispatch (deadline=30→45s)
              → Skill.invoke (10-30s→15-45s)
                   → LLM call (30s→60s)

AgentTeams → Matrix poll (90s→120s)
           → Matrix sync (30s→60s)
           → Message send (60s→90s)

task_lifecycle → wait_for_stage (30s→60s)
```

**关键原则**: 外层超时必须 > 内层超时之和，避免外层提前 kill 内层仍在执行的任务。当前链路：`WorkerPool(45s) > Skill(15-45s) > LLM(60s)` 存在倒挂风险，建议 OpenAI Client 保持 60s 但 Skill 内部对 LLM 调用使用更短超时。

---

## 4. 保活脚本 — 本地版 `local_keepalive.sh`

### 4.1 脚本设计

与现有 `codespace_keepalive.sh` 互补，新增本地调试场景的保活脚本：

```bash
#!/bin/bash
# EnergyMesh Local Multi-Worker Keep-Alive Script
# 用途: 本地调试期间防止 Docker 容器休眠 / FastAPI 进程退出
# 运行: nohup bash scripts/local_keepalive.sh > runs/keepalive.log 2>&1 &

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${ROOT}/runs/keepalive.log"
HEARTBEAT_FILE="/tmp/energymesh_keepalive"
INTERVAL=180  # 3 分钟 (不建议过短，避免触发 rate-limit)

# 可配置的服务端口列表
ENERGYMESH_PORT="${ENERGYMESH_PORT:-8000}"
MATRIX_PORT="${AGENTTEAMS_MATRIX_PORT:-18080}"
ELEMENT_PORT="${AGENTTEAMS_ELEMENT_PORT:-18088}"
MANAGER_PORT="${AGENTTEAMS_MANAGER_PORT:-18888}"
API_WORKER_PORT="${AGENTTEAMS_WORKER_PORT:-12925}"

# Docker 容器名称
CONTAINERS=(
    "agentteams-controller"
    "agentteams-manager"
    "agentteams-worker-energy-dispatcher"
)

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S')  $1" | tee -a "$LOG_FILE"
}

# ---- 辅助函数 ----

check_port() {
    local host="$1"
    local port="$2"
    local label="$3"
    if curl -fsS --max-time 5 "http://${host}:${port}" >/dev/null 2>&1; then
        return 0
    else
        log "WARN  ${label} (${host}:${port}) 不可达"
        return 1
    fi
}

ensure_container_running() {
    local name="$1"
    if ! docker inspect "$name" >/dev/null 2>&1; then
        # 容器不存在则跳过
        return 0
    fi
    local state
    state="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "unknown")"
    if [[ "$state" != "running" ]]; then
        log "WARN  容器 ${name} 状态=${state}，尝试启动..."
        docker start "$name" 2>&1 | tee -a "$LOG_FILE" || log "ERROR 无法启动 ${name}"
    fi
    # 确保 restart policy
    local policy
    policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name" 2>/dev/null || echo "none")"
    if [[ "$policy" == "no" || "$policy" == "" ]]; then
        docker update --restart unless-stopped "$name" 2>/dev/null || true
        log "INFO  ${name} restart policy → unless-stopped"
    fi
}

# ---- 健康检查汇总 ----

health_report() {
    local ok_count=0
    local fail_count=0
    local checks=()

    # EnergyMesh FastAPI
    if check_port "127.0.0.1" "$ENERGYMESH_PORT" "EnergyMesh API"; then
        ((ok_count++))
        checks+=("EnergyMesh:OK")
    else
        ((fail_count++))
        checks+=("EnergyMesh:DOWN")
    fi

    # AgentTeams Matrix
    if check_port "127.0.0.1" "$MATRIX_PORT" "Matrix Homeserver"; then
        ((ok_count++))
        checks+=("Matrix:OK")
    else
        ((fail_count++))
        checks+=("Matrix:DOWN")
    fi

    # AgentTeams Manager
    if check_port "127.0.0.1" "$MANAGER_PORT" "AgentTeams Manager"; then
        ((ok_count++))
        checks+=("Manager:OK")
    else
        checks+=("Manager:OFFLINE")
    fi

    # Element Web UI
    if check_port "127.0.0.1" "$ELEMENT_PORT" "Element UI"; then
        ((ok_count++))
        checks+=("Element:OK")
    else
        checks+=("Element:OFFLINE")
    fi

    # Docker 容器
    for c in "${CONTAINERS[@]}"; do
        if docker inspect "$c" >/dev/null 2>&1; then
            local st
            st="$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo "?")"
            if [[ "$st" == "running" ]]; then
                ((ok_count++))
                checks+=("${c}:running")
            else
                ((fail_count++))
                checks+=("${c}:${st}")
            fi
        fi
    done

    log "HEALTH ${ok_count}/${ok_count+fail_count} 通过 | ${checks[*]}"
    return "$fail_count"
}

# ---- 主循环 ----

log "=== EnergyMesh Local Keep-Alive Started ==="
log "PID: $$  INTERVAL: ${INTERVAL}s"
log ""

# 首次启动：确保容器运行且 restart policy 正确
for c in "${CONTAINERS[@]}"; do
    ensure_container_running "$c"
done

trap 'log "=== Keep-Alive Stopped ==="; exit 0' INT TERM

while true; do
    # 写入心跳文件
    touch "$HEARTBEAT_FILE"

    # 执行健康检查
    health_report

    # 额外保活操作：
    # 触碰 workspace 文件防止某些 IDE/filesystem-watch 超时
    touch "${ROOT}/.keepalive" 2>/dev/null || true

    sleep "$INTERVAL"
done
```

### 4.2 使用方法

```bash
# 1. 赋予执行权限
chmod +x scripts/local_keepalive.sh

# 2. 后台启动
nohup bash scripts/local_keepalive.sh > runs/keepalive.log 2>&1 &
echo $! > runs/keepalive.pid

# 3. 查看日志
tail -f runs/keepalive.log

# 4. 停止
kill $(cat runs/keepalive.pid) 2>/dev/null
```

---

## 5. 超时配置修改指南

### 5.1 按优先级排序的修改清单

#### P0 — 立即修改 (解决当前高频超时)

**文件: `src/energymesh/model_gateway.py`**
```python
# 行 145-149: OpenAI 客户端超时
client = OpenAI(api_key=config.api_key, base_url=base_url, timeout=60)  # 原 30
# 以及 httpx 代理客户端:
http_client=httpx.Client(proxy=proxy_url, timeout=60)
```

**文件: `src/energymesh/orchestrator_v2.py`**
```python
# 行 244: Perception Skill
timeout_seconds=20.0,  # 原 15.0

# 行 268: Dispatch Skill
timeout_seconds=45.0,  # 原 30.0

# 行 291: Audit Skill
timeout_seconds=30.0,  # 原 20.0

# 行 351-406: WorkerSpec 注册
WorkerSpec(..., default_timeout=45.0)  # 针对 dispatch_worker 和 dispatch_worker_backup
```

**文件: `src/energymesh/agent_worker.py`**
```python
# 行 57: AgentWorker 默认超时
timeout_seconds: float = 45.0  # 原 30.0
```

#### P1 — 次要调整

**文件: `src/energymesh/orchestrator_v2.py`**
```python
# 行 102: wait_for_stage
def wait_for_stage(self, stage: TaskLifecycleStage, timeout: float = 60.0) -> bool:  # 原 30.0

# 行 316: Execution Skill
timeout_seconds=25.0,  # 原 20.0

# 行 337: Approval Skill
timeout_seconds=15.0,  # 原 10.0
```

**环境变量: `.env.agentteams.local`**
```bash
# 新增环境变量
AGENTTEAMS_MATRIX_POLL_TIMEOUT=120  # 原默认 90s
```

### 5.2 环境变量统一管理方案

在 `.env.example` 中新增超时相关变量，便于不同环境差异化配置：

```bash
# 新增超时配置 (可选覆盖)
ENERGYMESH_LLM_TIMEOUT=60
ENERGYMESH_SKILL_TIMEOUT_DEFAULT=45
ENERGYMESH_WORKER_TIMEOUT_DEFAULT=45
AGENTTEAMS_MATRIX_POLL_TIMEOUT=120
AGENTTEAMS_MATRIX_SYNC_TIMEOUT=60000
```

---

## 6. Docker 容器自动恢复

### 6.1 容器 restart policy 一键设置

```bash
#!/bin/bash
# scripts/setup_container_restart.sh
# 一次性设置所有 AgentTeams 容器的自动重启策略

CONTAINERS=(
    "agentteams-controller"
    "agentteams-manager"
    "agentteams-worker-energy-dispatcher"
)

for c in "${CONTAINERS[@]}"; do
    if docker inspect "$c" >/dev/null 2>&1; then
        echo -n "${c}: "
        docker update --restart unless-stopped "$c"
    else
        echo "${c}: 不存在，跳过"
    fi
done

echo ""
echo "当前容器 restart policy:"
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null | grep -E "agentteams|energymesh" || echo "  (无)"
```

### 6.2 docker-compose.yml 增强

当前 `docker-compose.yml` 已包含 `restart: unless-stopped`，建议补充：

```yaml
services:
  energymesh:
    # ... 现有配置 ...
    restart: unless-stopped
    # 新增健康检查
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    # 新增资源限制
    deploy:
      resources:
        limits:
          memory: 512M
```

---

## 7. 验证与调试检查清单

### 阶段 1: 保活脚本验证 (预计 10 分钟)

- [ ] **1.1** 部署 `local_keepalive.sh` 到 `scripts/` 目录
- [ ] **1.2** 后台启动保活脚本: `nohup bash scripts/local_keepalive.sh > runs/keepalive.log 2>&1 &`
- [ ] **1.3** 等待 3 分钟后检查日志: `tail -20 runs/keepalive.log`
  - 预期: 看到 `HEALTH N/M 通过` 日志，无 ERROR
- [ ] **1.4** 验证心跳文件存在: `ls -la /tmp/energymesh_keepalive`
- [ ] **1.5** 停止 EnergyMesh API (模拟 crash): `kill <pid>`
  - 等待 3 分钟观察保活日志是否记录 WARN
- [ ] **1.6** 手动重启 EnergyMesh 再观察日志是否恢复 OK

### 阶段 2: 超时配置验证 (预计 15 分钟)

- [ ] **2.1** 按 5.1 节 P0 清单逐文件修改超时参数
- [ ] **2.2** 运行现有测试确保无回归: `make test`
- [ ] **2.3** 启动 EnergyMesh: `make run` 或 `scripts/start_agentteams_demo.sh`
- [ ] **2.4** 触发一次完整调度流程:
  ```bash
  curl -X POST http://127.0.0.1:8000/api/execute \
    -H "Content-Type: application/json" \
    -d '{"scenario_id": "demo", "trigger": "manual_dispatch"}'
  ```
- [ ] **2.5** 观察控制台日志，确认无 TIMEOUT 错误
- [ ] **2.6** 查看 TaskRecord 中的 WorkerResult，确认 `status != "timeout"`

### 阶段 3: 容器恢复验证 (预计 10 分钟)

- [ ] **3.1** 运行 `scripts/setup_container_restart.sh`
- [ ] **3.2** 验证 restart policy: `docker inspect agentteams-controller | jq '.[0].HostConfig.RestartPolicy'`
- [ ] **3.3** 模拟容器 crash: `docker stop agentteams-worker-energy-dispatcher`
- [ ] **3.4** 等待 10 秒后检查: `docker ps -a | grep agentteams-worker`
  - 预期: 容器状态为 `Up` (自动重启)
- [ ] **3.5** 恢复: `docker start agentteams-worker-energy-dispatcher`

### 阶段 4: 端到端多 Worker 协同验证 (预计 20 分钟)

- [ ] **4.1** 确保 Matrix + AgentTeams 全栈运行
  ```bash
  scripts/start_agentteams_demo.sh
  ```
- [ ] **4.2** 通过 Web UI (`http://127.0.0.1:8000`) 发送调度指令
- [ ] **4.3** 验证 5 个 Worker 全部在线:
  ```bash
  curl http://127.0.0.1:8000/api/agentteams/runtime | jq '.workers'
  ```
- [ ] **4.4** 触发多轮调度，观察 Worker 协作流程是否完整 (Perception → Dispatch → Audit → Execution)
- [ ] **4.5** 故意制造网络延迟 (如代理断开) 验证超时兜底机制触发
- [ ] **4.6** 检查 evidence 目录下生成的追踪文件: `ls -la runs/`

---

## 8. 故障排查速查表

| 症状 | 可能原因 | 排查步骤 |
|------|----------|----------|
| `HEALTH Matrix:DOWN` | Matrix 容器未启动 | `docker ps -a \| grep agentteams-controller` |
| `HEALTH EnergyMesh:DOWN` | uvicorn 进程退出 | `ps aux \| grep uvicorn`，查看 `runs/` 下日志 |
| `WorkerResult status=timeout` | Skill 超时偏短 | 检查对应 Skill 的 `timeout_seconds`，对照 3.1 表 |
| `UNEXPECTED_EOF_WHILE_READING` | DeepSeek API 超时 | 设置 `ENERGYMESH_MODEL_PROXY` 或增大 OpenAI timeout |
| 容器频繁重启 | 内存不足或配置错误 | `docker logs agentteams-controller --tail 50` |
| 保活脚本 pid 丢失 | 终端会话关闭 | 使用 `nohup` + 写入 pid 文件；考虑用 `launchd`/`systemd` |
| Matrix poll timeout | `AGENTTEAMS_MATRIX_POLL_TIMEOUT` 过短 | `echo $AGENTTEAMS_MATRIX_POLL_TIMEOUT`，按 5.1 调整 |

---

## 9. 建议执行顺序

```
Phase 1: 保活脚本 (30 分钟)
  ├── 1. 编写 & 部署 local_keepalive.sh
  ├── 2. 后台启动并验证日志
  └── 3. 确认心跳文件生成

Phase 2: 超时配置 (25 分钟)
  ├── 1. 修改 P0 超时参数 (model_gateway, orchestrator_v2, agent_worker)
  ├── 2. 运行 make test
  └── 3. 启动服务并触发调度验证

Phase 3: 容器恢复 (15 分钟)
  ├── 1. 设置 restart policy
  ├── 2. 模拟 crash 验证自动恢复
  └── 3. 添加 docker-compose healthcheck

Phase 4: 端到端验证 (20 分钟)
  ├── 1. 全栈启动
  ├── 2. 多轮调度测试
  └── 3. 故障注入验证
```

---

## 10. 风险边界

- **严禁** 在 `SIMULATION_MODE=false` 或 `ALLOW_PRODUCTION_WRITE=true` 环境下运行保活脚本
- 超时配置仅涉及调试与 LLM 调用链路，不影响安全审计 (`audit.py`) 的边界检查逻辑
- 保活脚本仅轮询本地服务健康状态，**不发送任何数据到外部**
- 所有修改必须通过 `make verify` (lint + typecheck + test) 后方可提交

---

*本文档待用户确认后转化为正式执行方案。*