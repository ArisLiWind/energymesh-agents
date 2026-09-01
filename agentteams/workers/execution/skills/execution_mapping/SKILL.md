# execution_mapping

Map only the current audited and, when required, Human-approved candidate through
`energymesh-control`.

- Input: task/version/context/candidate IDs, audit, Human event and idempotency key.
- Output: simulation commands, receipts, readback and verification evidence.
- Reject stale IDs, missing approval or unsafe runtime flags.
- Deviation above tolerance stops execution and requests `approval_rollback`.
- Simulation only; real device contact must remain zero.
