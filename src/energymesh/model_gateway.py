from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class StoredModelConfig:
    agent_id: str
    base_url: str
    api_key: str
    model: str
    connection_status: str = "未测试"
    last_error: str | None = None


AGENT_SYSTEM_PROMPTS = {
    "team_leader": (
        "你是 EnergyMesh 里和用户长期协作的 AI 工程师。你首先要像正常、自然、聪明的通用 AI 一样聊天，"
        "用户问你好、闲聊、解释概念或表达不满时，都要直接回应，不要把普通对话改写成流程日志。"
        "你同时能阅读当前右侧 3D 园区沙盘上下文：发电、储能、用电、电网、限发、购电和预览流向。"
        "如果用户只是讨论能源概念，直接解释；如果用户问当前园区哪里不对，先基于传入的沙盘上下文回答。"
        "只有当用户明确要求优化、模拟、预览、调整、采用、执行或改变园区运行方式时，才建议生成新方案预览。"
        "新方案必须围绕可见电流变化说清楚：哪条线消失、哪条线变粗、储能是充电还是放电、购电和限发如何变化。"
        "不要向用户暴露 perception/dispatch/audit/worker 路由，除非用户明确问系统内部怎么实现。"
        "未经用户明确采用或批准，不要声称已经执行真实设备控制。"
    ),
    "perception_agent": (
        "你是感知 Agent，负责获取并校验园区能源数据，包括负荷、光伏、储能 SOC、"
        "设备状态、生产计划和异常信号。你只能解释数据可信度、异常与任务有效性，"
        "不能生成调度方案或执行设备动作。"
    ),
    "dispatch_agent": (
        "你是调度 Agent，负责基于已核验上下文生成园区微电网受限策略脚本草案，"
        "脚本用于表达充电、放电、备用容量和异常降级逻辑，而不是直接写设备。"
        "你可以解释策略、成本和约束权衡，但不能绕过审核、沙箱回放或人工审批直接执行。"
    ),
    "forecast_agent": (
        "你是预测 Agent，负责基于感知 Agent 的状态快照和历史/知识库线索，判断未来负荷、"
        "光伏、变压器温度、储能 SOC 和风险窗口。你只能输出预测、趋势和异常窗口，"
        "不能生成调度方案、不能审核、不能执行。"
    ),
    "audit_agent": (
        "你是审核 Agent，负责静态审查策略脚本、沙箱回放脚本输出，并独立复算 SOC、"
        "功率、变压器、并网、生产计划、能量守恒和收益改善。不可验证或违反安全边界时默认不放行。"
    ),
    "execution_agent": (
        "你是执行 Agent，负责把获批策略脚本的确定性输出映射为结构化幂等命令并核对计划与实际结果。"
        "当前系统只允许本地模拟，不能连接真实 EMS、PCS、BMS 或生产设备。"
    ),
}

AGENT_ALIASES = {
    "leader": "team_leader",
    "team": "team_leader",
    "perception": "perception_agent",
    "forecast": "forecast_agent",
    "prediction": "forecast_agent",
    "dispatch": "dispatch_agent",
    "audit": "audit_agent",
    "execute": "execution_agent",
    "execution": "execution_agent",
}


def normalize_agent_id(agent_id: str) -> str:
    normalized = AGENT_ALIASES.get(agent_id, agent_id)
    if normalized not in AGENT_SYSTEM_PROMPTS:
        raise ValueError("unknown agent")
    return normalized


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * 8
    return f"{api_key[:3]}{'•' * 8}{api_key[-4:]}"


def normalize_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("base_url is required")
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url must be an absolute URL")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if parsed.netloc == "api.openai.com" and path in {"", "/"}:
        path = "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _deepest_error_message(error: BaseException) -> str | None:
    cause = error.__cause__
    message = None
    while cause is not None:
        message = str(cause)
        cause = cause.__cause__
    return message


def describe_model_error(error: BaseException) -> str:
    primary = str(error) or error.__class__.__name__
    cause = _deepest_error_message(error)
    message = primary if not cause or cause == primary else f"{primary} ({cause})"
    if "UNEXPECTED_EOF_WHILE_READING" in message or "SSL_ERROR_SYSCALL" in message:
        return (
            f"{message}. DeepSeek HTTPS 握手被中断；如果域名被解析到 198.18.x.x，"
            "通常说明本机代理处于 fake-ip/TUN 模式，但 Python 后端没有走代理。"
            "请设置 ENERGYMESH_MODEL_PROXY，例如 http://127.0.0.1:7890 或 "
            "socks5://127.0.0.1:7890，然后重启后端。"
        )
    return message


def chat_with_agent_config(
    config: StoredModelConfig,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    try:
        from openai import OpenAI
        from openai.types.chat import ChatCompletionMessageParam
    except ImportError as error:
        raise RuntimeError("openai package is not installed") from error

    base_url = normalize_base_url(config.base_url)
    proxy_url = os.getenv("ENERGYMESH_MODEL_PROXY")
    if proxy_url:
        import httpx

        client = OpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=30,
            http_client=httpx.Client(proxy=proxy_url, timeout=30),  # type: ignore[arg-type]
        )
    else:
        client = OpenAI(api_key=config.api_key, base_url=base_url, timeout=30)
    messages = cast(
        Iterable[ChatCompletionMessageParam],
        [
            {"role": "system", "content": AGENT_SYSTEM_PROMPTS[config.agent_id]},
            *(history or []),
            {"role": "user", "content": message},
        ],
    )
    try:
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
        )
    except Exception as error:
        raise RuntimeError(describe_model_error(error)) from error
    content = response.choices[0].message.content
    return content or ""
