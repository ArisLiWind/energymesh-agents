from __future__ import annotations

from energymesh.models import (
    AuditDecision,
    AuditFinding,
    AuditReport,
    DispatchPlan,
    Scenario,
)


class IndependentSafetyAuditor:
    """Fail-closed deterministic audit, intentionally separate from optimization."""

    CHECKED_RULES = [
        "declared SOC policy",
        "realized SOC bounds",
        "battery power and temperature derating",
        "transformer import capacity",
        "grid interconnection import capacity",
        "production minimum-load plan",
        "interval energy balance",
        "flexible load authorization",
        "measurable improvement over original EMS policy",
    ]

    def audit(
        self, scenario: Scenario, plan: DispatchPlan, baseline: DispatchPlan
    ) -> AuditReport:
        site = scenario.site
        findings: list[AuditFinding] = []

        if plan.declared_min_soc < site.safety_min_soc:
            findings.append(
                AuditFinding(
                    code="SOC_POLICY_UNDERRUN",
                    severity="critical",
                    message=(
                        f"候选声明最小 SOC {plan.declared_min_soc:.0%}，"
                        f"低于站点硬下限 {site.safety_min_soc:.0%}。"
                    ),
                )
            )

        tolerance = 0.05
        for point, forecast in zip(plan.points, scenario.forecast, strict=True):
            if point.soc_end < site.safety_min_soc - 1e-6:
                findings.append(
                    AuditFinding(
                        code="SOC_BELOW_MIN",
                        severity="critical",
                        message="计划 SOC 低于硬安全下限。",
                        interval=point.interval,
                    )
                )
            if point.soc_end > site.safety_max_soc + 1e-6:
                findings.append(
                    AuditFinding(
                        code="SOC_ABOVE_MAX",
                        severity="critical",
                        message="计划 SOC 高于硬安全上限。",
                        interval=point.interval,
                    )
                )
            discharge_limit = site.battery_discharge_max_kw
            if forecast.battery_temperature_c >= 45:
                discharge_limit *= site.alarm_discharge_derate
            if point.discharge_kw > discharge_limit + tolerance:
                findings.append(
                    AuditFinding(
                        code="TEMPERATURE_DERATE_EXCEEDED",
                        severity="critical",
                        message="高温期间计划放电功率超过降额限制。",
                        interval=point.interval,
                    )
                )
            if point.charge_kw > site.battery_charge_max_kw + tolerance:
                findings.append(
                    AuditFinding(
                        code="CHARGE_POWER_EXCEEDED",
                        severity="critical",
                        message="计划充电功率超过 PCS 上限。",
                        interval=point.interval,
                    )
                )
            transformer_limit = site.transformer_capacity_kw
            if (
                forecast.transformer_temperature_c
                >= site.transformer_temperature_limit_c
                and forecast.transformer_redundant_temperature_c
                >= site.transformer_temperature_limit_c
            ):
                transformer_limit *= site.transformer_hot_derate_factor
            if point.grid_import_kw > transformer_limit + tolerance:
                findings.append(
                    AuditFinding(
                        code="TRANSFORMER_CAPACITY_EXCEEDED",
                        severity="critical",
                        message=(
                            f"计划购电功率超过当前温度下变压器容量 {transformer_limit:.1f} kW。"
                        ),
                        interval=point.interval,
                    )
                )
            if point.grid_import_kw > site.grid_interconnection_limit_kw + tolerance:
                findings.append(
                    AuditFinding(
                        code="GRID_INTERCONNECTION_EXCEEDED",
                        severity="critical",
                        message="计划购电功率超过并网点许可容量。",
                        interval=point.interval,
                    )
                )
            served_load = point.load_kw - point.flexible_load_shed_kw
            if served_load < forecast.production_min_load_kw - tolerance:
                findings.append(
                    AuditFinding(
                        code="PRODUCTION_PLAN_VIOLATED",
                        severity="critical",
                        message="柔性响应后供电负荷低于生产计划最小需求。",
                        interval=point.interval,
                    )
                )
            balance = (
                point.grid_import_kw
                + point.pv_kw
                - point.pv_curtailment_kw
                + point.discharge_kw
                - point.charge_kw
                + point.flexible_load_shed_kw
                - point.load_kw
            )
            if abs(balance) > tolerance:
                findings.append(
                    AuditFinding(
                        code="POWER_BALANCE_INVALID",
                        severity="critical",
                        message=f"功率平衡残差 {balance:.3f} kW 超出容差。",
                        interval=point.interval,
                    )
                )

        baseline_cost = self._recompute_total_cost(scenario, baseline)
        plan_cost = self._recompute_total_cost(scenario, plan)
        improvement = baseline_cost - plan_cost
        improvement_ratio = improvement / baseline_cost if baseline_cost else 0.0
        if improvement <= 0.01:
            findings.append(
                AuditFinding(
                    code="NO_MEASURABLE_IMPROVEMENT",
                    severity="critical",
                    message="新方案未证明在相同预测条件下优于原 EMS 策略。",
                )
            )
        else:
            findings.append(
                AuditFinding(
                    code="BASELINE_IMPROVEMENT_VERIFIED",
                    severity="info",
                    message=(
                        f"相对原 EMS 策略预计节省 {improvement:.2f} 元（{improvement_ratio:.1%}）。"
                    ),
                )
            )

        has_critical = any(item.severity == "critical" for item in findings)
        shed_energy = plan.metrics.shed_energy_kwh
        if shed_energy > 0.01 and not has_critical:
            findings.append(
                AuditFinding(
                    code="HUMAN_APPROVAL_REQUIRED",
                    severity="warning",
                    message=f"计划削减柔性负荷 {shed_energy:.2f} kWh，执行前必须人工审批。",
                )
            )
            decision = AuditDecision.REQUIRES_APPROVAL
        elif has_critical:
            decision = AuditDecision.REJECTED
        else:
            decision = AuditDecision.APPROVED

        if not findings:
            findings.append(
                AuditFinding(
                    code="ALL_HARD_CONSTRAINTS_PASSED",
                    severity="info",
                    message="全部硬约束与功率平衡校验通过。",
                )
            )
        return AuditReport(
            plan_id=plan.plan_id,
            decision=decision,
            findings=findings,
            checked_rules=self.CHECKED_RULES,
            baseline_total_cost_yuan=round(baseline_cost, 2),
            improvement_yuan=round(improvement, 2),
            improvement_ratio=round(improvement_ratio, 4),
        )

    @staticmethod
    def _recompute_total_cost(scenario: Scenario, plan: DispatchPlan) -> float:
        site = scenario.site
        dt = site.interval_minutes / 60
        energy = sum(
            point.grid_import_kw * forecast.tariff_yuan_per_kwh * dt
            for point, forecast in zip(plan.points, scenario.forecast, strict=True)
        )
        demand = max(point.grid_import_kw for point in plan.points) * (
            site.demand_charge_yuan_per_kw
        )
        degradation = sum(
            (point.charge_kw + point.discharge_kw) * dt * site.degradation_yuan_per_kwh
            for point in plan.points
        )
        return energy + demand + degradation
