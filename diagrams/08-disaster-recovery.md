# 08 / Disaster recovery

All targets are architectural assumptions for this proof of concept, not
measured or agreed SLAs.

```mermaid
flowchart TB
    subgraph P["Primary region"]
        CH1["CloudHub 2.0<br/>3 replicas per application"]
        SF1[("Snowflake primary<br/>Time Travel 1–7 days")]
    end
    subgraph S["Secondary region"]
        CH2["CloudHub 2.0<br/>warm standby"]
        SF2[("Snowflake replica<br/>continuous replication")]
    end
    subgraph B["Durable"]
        OS[("Object store<br/>landing files, versioned, 90 days")]
        EX[("Exchange<br/>immutable artefacts")]
        GIT[("Git<br/>configuration + IaC")]
    end
    SF1 -.replication.-> SF2
    CH1 -.DNS failover, 30 min.-> CH2
    OS --> SF1
    EX --> CH1
    EX --> CH2
    GIT --> EX
```

## Recovery paths by failure

```mermaid
flowchart TB
    F{"What failed?"}
    F -->|worker| W["Load balancer removes it<br/><b>RTO 0 / RPO 0</b>"]
    F -->|application| A["Restart or roll back<br/><b>RTO 5 min / RPO 0</b>"]
    F -->|region| R["DNS failover + promote the replica<br/><b>RTO 30 min / RPO 0 for APIs</b>"]
    F -->|object dropped| O["UNDROP within Time Travel<br/><b>RTO 15 min / RPO 0</b>"]
    F -->|corrupt CORE| C["Clone to before the load / diff /<br/>fix / re-run 06 and 07<br/><b>RTO 2 h / RPO 1 h</b>"]
    F -->|corrupt RAW| RR["Re-ingest from source<br/><b>RTO 4 h / RPO 24 h</b>"]
    F -->|account loss| AL["Fail over to the replicated account<br/><b>RTO 4 h / RPO 1 h</b>"]
    F -->|credential| CR["Revoke / rotate / redeploy /<br/>establish blast radius from audit"]
```

Two rows carry the design argument:

- **The APIs have RPO 0 because they hold no state.** All state is in Snowflake
  or a source system. The object stores hold only idempotency keys and breaker
  flags, both safe to lose.
- **Corrupt CORE is a 2-hour re-run, not a restore**, because CORE is rebuildable
  from RAW. If CORE were the only copy this box would say "restore from backup"
  and the number would be much larger.

## Degradation ladder

The platform degrades in the direction of the deterministic.

```mermaid
flowchart LR
    F["Full response<br/>profile / orders / support /<br/>loyalty / analytics / churn / AI"]
    F -->|AI provider down| D1["No narrative<br/>score and drivers remain"]
    D1 -->|one source stale| D2["partial: true<br/>degradedFields names it"]
    D2 -->|Snowflake unavailable| D3["503 retryable<br/>service desk falls back to the CRM"]
    D3 -->|region down| D4["Failover, 30 min"]
```

## Exercise schedule

| Exercise | Frequency | Success criterion |
|---|---|---|
| Time Travel restore | Monthly | < 15 min, data verified |
| Rebuild CORE in a clone | Monthly | < 2 h, DQ suite matches expectations |
| Region failover in UAT | Quarterly | < 30 min, smoke test green |
| Chaos: kill a worker | Monthly | No client-visible error |
| Chaos: block Snowflake | Quarterly | 503 retryable, breaker opens, alert fires |
| Chaos: fail the AI provider | Quarterly | Degradation visible, no 500s |
| Credential rotation | Quarterly | No outage |

The fault-injection hooks in the mock services exist so the last three can be
exercised in CI, not only in UAT.
