from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredModelConfig:
    agent_id: str
    base_url: str
    api_key: str
    model: str
    connection_status: str = "未测试"
    last_error: str | None = None


AGENT_SYSTEM_PROMPTS = {
    "perception_agent": (
        "你是感知 Agent，负责获取并校验园区能源数据，包括负荷、光伏、储能 SOC、"
        "设备状态、生产计划和异常信号。你只能解释数据可信度、异常与任务有效性，"
        "不能生成调度方案或执行设备动作。"
    ),
    "dispatch_agent": (
        "你是调度 Agent，负责基于已核验上下文生成园区微电网调度候选方案。"
        "你可以解释策略、成本和约束权衡，但不能绕过审核或人工审批直接执行。"
    ),
    "audit_agent": (
        "你是审核 Agent，负责独立复算 SOC、功率、变压器、并网、生产计划、"
        "能量守恒和收益改善。不可验证或违反安全边界时默认不放行。"
    ),
    "execution_agent": (
        "你是执行 Agent，负责把获批方案映射为结构化幂等命令并核对计划与实际结果。"
        "当前系统只允许本地模拟，不能连接真实 EMS、PCS、BMS 或生产设备。"
    ),
}

AGENT_ALIASES = {
    "perception": "perception_agent",
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


def chat_with_agent_config(config: StoredModelConfig, message: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("openai package is not installed") from error

    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    response = client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": AGENT_SYSTEM_PROMPTS[config.agent_id]},
            {"role": "user", "content": message},
        ],
    )
    content = response.choices[0].message.content
    return content or ""
