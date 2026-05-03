# Phase 6 Rollout Go/No-Go Checklist

Use this checklist as a release gate for Phase 6 control-plane rollout.

Release ID: ____________________  
Date (UTC): ____________________  
Environment: ____________________  
Release Manager: ____________________

## Decision Rule

- GO only if all Critical gates are PASS.
- NO-GO if any Critical gate is FAIL.
- Conditional GO only if all Critical gates are PASS and all exceptions have owner + due date.

## 1) Functional Quality Gates (Critical)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Smoke suite | 100% pass on 3 consecutive runs |  |  |
| Regression suite | >= 99.5% pass and 0 critical failures |  |  |
| Flaky tests | < 1% over last 20 CI runs |  |  |
| API contracts | 100% pass for execute/apply + audit endpoints |  |  |

## 2) Control-Plane Safety Gates (Critical)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Global kill switch | 100% apply attempts blocked when OFF |  |  |
| Type kill switch | 100% blocked types denied, 0 false allows |  |  |
| Policy guardrails | 100% out-of-policy apply attempts blocked with policy code |  |  |
| Apply idempotency | 0 duplicate state transitions on 1,000 replayed apply requests |  |  |

## 3) Audit and Traceability Gates (Critical)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Decision events | 100% apply attempts emit exactly one decision event (`optimization_apply_allowed` or `optimization_apply_blocked`) |  |  |
| Lifecycle consistency | 100% successful applies emit `optimization_recommendation_applied`; 100% rollbacks emit `optimization_recommendation_rolled_back` |  |  |
| Required identifiers | >= 99.9% audit events include `correlation_id` and `recommendation_id` |  |  |
| Blocked reason code | 100% blocked apply events include `reason_code` |  |  |

## 4) Reliability and Performance Gates (Critical)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Execute dry-run p95 latency | <= 300 ms |  |  |
| Execute apply p95 latency | <= 500 ms |  |  |
| API 5xx rate (24h soak) | <= 0.1% |  |  |
| Total API error rate (excluding expected policy/switch blocks) | <= 1.5% |  |  |
| Availability (24h soak) | >= 99.9% |  |  |

## 5) Incident Readiness Gates (Critical)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Disable global apply drill | <= 2 minutes |  |  |
| Disable one recommendation type drill | <= 3 minutes |  |  |
| Audit verification after simulated incident | <= 10 minutes |  |  |
| Rollback drill success | 100% over 10 trial recommendations |  |  |

## 6) Monitoring and Alerting Gates (Important)

| Gate | Threshold | Status (PASS/FAIL) | Evidence |
|---|---:|---|---|
| Dashboard coverage | Live metrics for apply allowed/blocked, rollback ratio, status distribution |  |  |
| Alert test | Alerts configured and test-fired for 5xx spike, missing decision events, rollback spike |  |  |

## 7) Canary Rollout Gates (Critical)

| Stage | Threshold | Status (PASS/FAIL) | Evidence |
|---|---|---|---|
| 5% traffic for 2h | 5xx <= 0.2%, rollback ratio < 1%, missing decision events < 0.1% |  |  |
| 25% traffic for 8h | 5xx <= 0.2%, rollback ratio < 1.5%, p95 latency within +10% baseline |  |  |
| 50% traffic for 24h | 5xx <= 0.1%, rollback ratio < 2%, no Sev-1/Sev-2 incidents |  |  |

## 8) Automatic No-Go Triggers

- Any confirmed lifecycle data integrity issue.
- Missing decision events > 0.1% in any validation window.
- Sev-1 incident during canary.
- 5xx > 1% for 5 continuous minutes.
- Rollback ratio > 3% for 30 minutes.
- Any kill-switch drill failure.

## 9) Exceptions (Required for Conditional GO)

| Exception | Risk | Mitigation | Owner | Due Date |
|---|---|---|---|---|
|  |  |  |  |  |

## 10) Final Sign-Off

| Role | Name | Decision (GO/NO-GO) | Timestamp (UTC) |
|---|---|---|---|
| Engineering Lead |  |  |  |
| SRE/Platform Owner |  |  |  |
| Product Owner |  |  |  |
| Incident Commander (On-call) |  |  |  |

Final Release Decision: GO / NO-GO  
Approved By: ____________________  
Timestamp (UTC): ____________________