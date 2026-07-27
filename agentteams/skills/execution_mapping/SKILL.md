# execution_mapping

Use this Skill only after a plan is approved or explicitly requires no approval.

Inputs: approved dispatch plan, audit decision, optional approval ID.

Outputs: idempotent EMS, PCS, and load-control commands plus execution confirmation.

Local implementation: `energymesh.simulator.SimulationExecutor`.

Safety: local simulation only; production writes are disabled.
