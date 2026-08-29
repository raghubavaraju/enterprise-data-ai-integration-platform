# 09 / Deployment topology

## Cloud

```mermaid
flowchart TB
    subgraph CDN["Edge"]
        WAF["WAF + TLS termination"]
    end
    subgraph AP["Anypoint Platform"]
        AM["API Manager<br/>policies / SLA tiers / analytics"]
        EX["Exchange<br/>specs / fragments / artefacts"]
        RM["Runtime Manager<br/>secure properties / deployment"]
        MON["Anypoint Monitoring"]
    end
    subgraph CH["CloudHub 2.0 / private space"]
        direction TB
        E1["customer-experience-api<br/>2 replicas / 0.2 vCore"]
        E2["ai-insights-api<br/>2 replicas"]
        P1["customer-360-process-api<br/>3 replicas"]
        P2["customer-intelligence-process-api<br/>2 replicas"]
        S1["snowflake-data-system-api<br/>3 replicas"]
        S2["crm-system-api"]
        S3["order-system-api"]
        S4["support-system-api"]
        S5["loyalty-system-api"]
    end
    subgraph CC["Container platform"]
        AI["ai-service<br/>2 replicas"]
    end
    subgraph SFC["Snowflake account"]
        WH1["ACME_INTEGRATION_WH<br/>XSMALL / multi-cluster ≤3 / 60 s suspend"]
        WH2["ACME_TRANSFORM_WH<br/>SMALL / 120 s suspend"]
        WH3["ACME_AI_WH<br/>SMALL / resource monitor, hard stop"]
        DB[("ACME_EDP")]
    end
    subgraph SRC["Source systems / on premises + SaaS"]
        CRM[("CRM")]
        OMS[("OMS")]
        SUP[("Support")]
        LOY[("Loyalty")]
    end

    WAF --> AM --> E1 & E2
    E1 --> P1
    E2 --> P2
    P1 --> S1 & S2 & S3 & S4 & S5
    P2 --> S1
    P2 --> AI
    S1 --> WH1 --> DB
    AI --> WH3 --> DB
    WH2 --> DB
    S2 --> CRM
    S3 --> OMS
    S4 --> SUP
    S5 --> LOY
    RM -.deploys.-> CH
    EX -.artefacts.-> RM
    CH -.telemetry.-> MON
```

## Local, what `make run` starts

```mermaid
flowchart TB
    subgraph L["One machine / no cloud account"]
        E[":8080 experience-api<br/>+ mock OAuth token endpoint"]
        P[":8091 process-api"]
        S[":8090 system-api"]
        D[":8092 snowflake-data-api<br/><b>the only warehouse owner</b>"]
        A[":8087 ai-service"]
        M1[":8081 CRM"]
        M2[":8082 orders"]
        M3[":8083 support"]
        M4[":8084 loyalty"]
        M5[":8085 catalogue"]
        W[("DuckDB<br/>acme_edp.duckdb")]
    end
    E --> P --> S --> D --> W
    P --> A --> D
    S --> M1 & M2 & M3 & M4 & M5
```

The warehouse has a single owner process because DuckDB permits one writer, and
every other service reaches it over the Snowflake SQL API contract. That
constraint pushed the AI service to read through the data platform's API rather
than opening the file, which is the better architecture in cloud mode too, for
reasons that have nothing to do with DuckDB.

## Mapping between the two

| Cloud | Local | Identical? |
|---|---|---|
| MuleSoft experience layer | `services/gateway/experience_layer.py` | Same contract, same policies |
| MuleSoft process layer | `services/gateway/process_layer.py` | Same contract, same degradation |
| MuleSoft system layer | `services/gateway/system_layer.py` | Same contract, same normalisation |
| Snowflake SQL API | `services/data_api/app.py` | Same wire contract |
| AI service | `services/ai_service/` | **Identical code**, different provider |
| Snowflake | DuckDB + dialect shim | Same portable SQL |
| Source systems | `services/mock_services/` | Same shapes and quirks |
