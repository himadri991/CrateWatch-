# CrateWatch SLA

## Purpose

This SLA defines the service level that CrateWatch promises to a museum, gallery, or courier during a monitored shipment. It covers the API, telemetry ingestion, alert delivery, and incident recovery. The values are prototype targets, not a commercial contract.

## Measurement window

- Rolling window: 15 minutes.
- Telemetry sample interval: 2 seconds.
- Local gap threshold: 10 seconds.
- Demo gap threshold: 4 seconds.
- SLA snapshot refresh: every dashboard poll, every 2 seconds.
- Measurement source: the `/api/sla` endpoint and the evidence files in `docs/`.

## Service level targets

| Metric | Definition | Target |
| --- | --- | --- |
| Telemetry availability | Successful telemetry requests divided by expected requests in the window | 99.5 percent or higher |
| API latency P95 | 95th percentile of API response time in the window | 300 ms or lower |
| Alert latency P95 | Time from `event_ts` to `detected_at` for alerting requests | 5 seconds or lower |
| Ingestion delay P95 | Time from `event_ts` to `received_ts` at the API | 30 seconds or lower |
| TTR S1 P95 | Time from `event_ts` to verified resolution for S1 incidents | 15 minutes or lower |
| TTR S2 P95 | Time from `event_ts` to verified resolution for S2 incidents | 60 minutes or lower |
| Data loss | Readings accepted by the edge agent but missing after recovery | 0 readings |
| RTO | Time to restore service after a process failure | 5 minutes or lower |

## Severity and TTR

| Severity | Example condition | Target TTR | Escalation |
| --- | --- | --- | --- |
| S1 | Shock at or above 8 g, temperature outside 15 to 25 C, evidence export failure during an active claim | 15 minutes | Registrar and courier lead, immediate |
| S2 | Humidity outside 40 to 60 percent, crate door open | 60 minutes | Courier lead |
| S3 | Telemetry gap longer than the threshold | 4 hours | Operations team |
| S4 | Battery below 20 percent | 24 hours | Operations team |

## Formula details

### Telemetry availability

```text
availability = 1 - (failed telemetry requests / expected telemetry requests)
```

Expected requests come from the 2 second sample interval and the number of active crates. A request that reaches the API and is accepted counts as available. A request that fails validation does not count as available.

### Alert latency

```text
alert_latency = detected_at - event_ts
```

Both timestamps are stored by the API. The control plane serializes the datetimes to UTC, so clock skew between the edge and the API is visible in the result. A production deployment should synchronize edge clocks with NTP and reject samples with an event time too far in the future.

### API latency

The API middleware records the duration of each request. The SLA snapshot reports the P95 and P99 from the in-memory sample list. The list is capped so memory use stays bounded.

### Ingestion delay

```text
ingestion_delay = received_ts - event_ts
```

This measures the delay from the crate event to the API receipt. It includes edge buffering time, so a long network outage will push this value up even when no data is lost.

### TTR

```text
TTR = resolved_at - event_ts
```

TTR covers detection, diagnosis, recovery, and verification. The controlled failure scenario measured each stage:

| Stage | Time |
| --- | --- |
| Detection | 0.000 s |
| Diagnosis | 2.019 s |
| Recovery | 2.012 s |
| Verification | 0.011 s |
| Total TTR | 4.031 s |

The dashboard also shows the live TTR P95. In the live snapshot it was 24.324 seconds because the second incident waited for a screenshot before resolution. The controlled TTR is the value used for the SLA claim.

## Breach handling

1. The dashboard marks a check as `BREACH` when the measured value misses the target.
2. The `/api/sla` response includes the current value, the target, the status, and the sample count.
3. The S1 metric filter and alarm in CloudWatch notify the operations team.
4. A TTR breach opens a post incident review. The review records the detection time, the recovery action, and the missed target.
5. A repeated API latency breach should trigger a cache or query optimization before the next shipment.

## Exclusions

The prototype has no planned maintenance window. A production SLA should exclude:

- Pre-approved maintenance announced at least 24 hours in advance.
- Failures caused by the customer network or sensor hardware.
- Force majeure events.
- Incidents caused by misuse of the demo token.

## Current measured results

| Metric | Result | Status |
| --- | --- | --- |
| Telemetry availability | 100.00 percent | Met |
| Alert latency P95 | 0.00 s | Met |
| API latency P95, live snapshot | 25.07 ms | Met |
| API latency P95, load test | 121.81 ms | Met |
| API latency P99, load test | 257.56 ms | Met |
| Ingestion delay P95 | 0.015 s | Met |
| TTR S1 P95, live snapshot | 24.324 s, or 0.405 min | Met |
| TTR S1, controlled scenario | 4.031 s, or 0.067 min | Met |
| RTO | 2.48 s | Met |
| Data loss after edge buffer recovery | 0 readings | Met |

## Known gaps

- The `/api/sla` endpoint P95 reached 947.60 ms under the synthetic load test. The endpoint meets the interactive dashboard use case but not a high frequency public API use case.
- The local measurements use one machine and simulated sensors. AWS network latency, EFS latency, and ALB behavior were not measured.
- The prototype has one API task. A task failure causes a short outage until ECS replaces it. The RTO target assumes the replacement starts within the configured health check interval.
- The SLA does not include a service credit or financial penalty. A commercial contract would need legal review.
