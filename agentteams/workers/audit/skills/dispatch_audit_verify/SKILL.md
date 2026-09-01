# dispatch_audit_verify

Independently verify immutable candidates through `energymesh-audit`.

- Input: candidate, original baseline and referenced current decision snapshot.
- Output: rejected, approved-low-risk, requires-Human-approval or blocked-unverifiable verdict.
- Recompute SOC, PCS, transformer, grid, balance, production, authorization and improvement rules.
- Missing/stale/mismatched evidence fails closed.
- Cannot modify a candidate, approve for a Human or call control tools.
