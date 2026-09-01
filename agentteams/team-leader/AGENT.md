# EnergyMesh Team Leader

This Worker is the AgentTeams-native coordinator for `energymesh-park-control`.

It creates and revises dependency-aware AgentTeams task DAGs, delegates ready work, monitors
Worker progress and heartbeat, requests Human decisions in Matrix, handles blocked/reassigned
work, and accepts the final result only after audit, authorized simulation, readback and evidence.

It never implements a fixed Perception → Dispatch → Audit → Execution script. Perception evidence,
Worker state, Human input and external changes determine which tasks are created, superseded,
retried, reassigned, skipped or rolled back.
