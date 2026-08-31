from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any


@dataclass(frozen=True)
class MCPToolResult:
    tool_name: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]


class EnergyMCPGateway:
    """Local MCP-style gateway for EMS/BMS/PCS/MES/forecast data."""

    def __init__(self, world_state_provider: Callable[[], dict[str, Any] | None] | None = None) -> None:
        self.world_state_provider = world_state_provider

    def get_energy_state(self, task: str) -> MCPToolResult:
        world_state = self.world_state_provider() if self.world_state_provider else None
        if world_state:
            output = {
                "source": "mcp://energymesh/world.current_state",
                "generated_at": datetime.now(UTC).isoformat(),
                "task": task,
                **world_state,
            }
            return MCPToolResult(
                tool_name="energy.get_state",
                input_payload={"task": task},
                output_payload=output,
            )

        load_delta_kw = self._load_delta_kw(task)
        base_load_mw = 6.0
        current_load_mw = round(base_load_mw + load_delta_kw / 1000, 3)
        available_capacity_mw = 2.4
        transformer_load_percent = min(96.0, round(78 + load_delta_kw / 100, 1))
        storage_soc_percent = 61
        pv_forecast_mw = 3.0
        peak_tariff_window = "18:00-22:00"
        production_min_load_mw = round(current_load_mw - 0.45, 3)
        output = {
            "source": "mcp://energymesh/energy.get_state",
            "generated_at": datetime.now(UTC).isoformat(),
            "task": task,
            "load_delta_kw": load_delta_kw,
            "current_load_mw": current_load_mw,
            "available_capacity_mw": available_capacity_mw,
            "transformer_load_percent": transformer_load_percent,
            "storage_soc_percent": storage_soc_percent,
            "pv_forecast_mw": pv_forecast_mw,
            "peak_tariff_window": peak_tariff_window,
            "production_min_load_mw": production_min_load_mw,
            "grid_import_limit_mw": 9.2,
            "device_status": {
                "ems": "online",
                "pcs": "healthy",
                "bms": "healthy",
                "mes": "production-plan-confirmed",
            },
        }
        return MCPToolResult(
            tool_name="energy.get_state",
            input_payload={"task": task},
            output_payload=output,
        )

    @staticmethod
    def _load_delta_kw(task: str) -> int:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kw|kW|KW|千瓦)", task)
        if match:
            return int(float(match.group(1)))
        mw_match = re.search(r"(\d+(?:\.\d+)?)\s*(mw|MW|兆瓦)", task)
        if mw_match:
            return int(float(mw_match.group(1)) * 1000)
        return 800
