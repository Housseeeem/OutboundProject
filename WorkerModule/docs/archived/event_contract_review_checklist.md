# Event Contract Review Checklist (v1)

## Submission Rules
- One row per event in [event_contract_intake_template.csv](event_contract_intake_template.csv)
- Include normal, retry, and failure events
- Mark status as `Proposed`, `Confirmed`, or `Deprecated`
- Provide one owner per module
- Use UTC ISO-8601 timestamps in examples

## Required Validation Gates
- Every event has non-empty `event_id`, `correlation_id`, `module`, `event_type`, `timestamp`
- `event_id` is globally unique and idempotency-safe
- `correlation_id` is propagated (not regenerated mid-chain)
- `decision_id` and `action_id` policy is explicit (`required/recommended/N/A`)
- Flow position references at least one predecessor event, except chain-start events
- Failure mode event is defined for each business event

## Worker Acceptance Criteria
- Event can be reconstructed in a full chain by `correlation_id`
- Outcome events (`reply_received`, `conversion`) can link to causally closest prior event
- Payload includes minimum business keys for KPI computation
- Contract ambiguity is resolved before status becomes `Confirmed`

## Freeze Policy
- After review, lock as Event Contract v1
- Any change requires versioned update (`v1` -> `v1.1`/`v2`) with migration notes
