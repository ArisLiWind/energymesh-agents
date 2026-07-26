from __future__ import annotations

from energymesh.audit import IndependentSafetyAuditor
from energymesh.models import AuditDecision
from energymesh.optimizer import DispatchOptimizer


def test_demo_has_96_quarter_hour_intervals(scenario) -> None:
    assert len(scenario.forecast) == 96
    assert scenario.site.interval_minutes == 15
    assert any(point.battery_temperature_c >= 45 for point in scenario.forecast)
    assert any(
        point.transformer_temperature_c >= scenario.site.transformer_temperature_limit_c
        for point in scenario.forecast
    )


def test_optimizer_generates_three_power_balanced_candidates(scenario) -> None:
    plans = DispatchOptimizer().optimize_candidates(scenario)

    assert [plan.profile for plan in plans] == [
        "economic_aggressive",
        "balanced",
        "conservative",
    ]
    for plan in plans:
        assert len(plan.points) == 96
        assert plan.metrics.peak_grid_kw <= scenario.site.transformer_capacity_kw
        assert plan.metrics.pv_self_consumption_ratio >= 0.99
        for point in plan.points:
            forecast = scenario.forecast[point.interval]
            transformer_limit = scenario.site.transformer_capacity_kw
            if forecast.transformer_temperature_c >= scenario.site.transformer_temperature_limit_c:
                transformer_limit *= scenario.site.transformer_hot_derate_factor
            assert point.grid_import_kw <= transformer_limit + 0.05
            residual = (
                point.grid_import_kw
                + point.pv_kw
                - point.pv_curtailment_kw
                + point.discharge_kw
                - point.charge_kw
                + point.flexible_load_shed_kw
                - point.load_kw
            )
            assert abs(residual) <= 0.05


def test_independent_audit_blocks_unsafe_reserve_and_gates_load_shed(scenario) -> None:
    optimizer = DispatchOptimizer()
    baseline = optimizer.build_baseline(scenario)
    plans = optimizer.optimize_candidates(scenario)
    reports = [IndependentSafetyAuditor().audit(scenario, plan, baseline) for plan in plans]
    decisions = {plan.profile: report.decision for plan, report in zip(plans, reports, strict=True)}

    assert decisions["economic_aggressive"] == AuditDecision.REJECTED
    assert decisions["balanced"] == AuditDecision.REQUIRES_APPROVAL
    assert decisions["conservative"] == AuditDecision.APPROVED
    assert all(report.improvement_yuan > 0 for report in reports)
