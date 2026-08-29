# 10 / Event-driven extension

**Designed, not built.** See [ADR-005](../docs/decisions/ADR-005-apis-versus-events.md)
for why, and [event-driven-architecture.md](../docs/event-driven-architecture.md)
for the full design.

```mermaid
flowchart TB
    subgraph SRC["Source systems"]
        CRM[("CRM")]
        OMS[("Orders")]
        SUP[("Support")]
        LOY[("Loyalty")]
    end
    subgraph PUB["System APIs publish<br/><i>canonical vocabulary, same as the sync path</i>"]
        CS["CRM System API"]
        OS["Order System API"]
        SS["Support System API"]
        LS["Loyalty System API"]
    end
    subgraph BUS["Event bus / Anypoint MQ, designed for Kafka"]
        T1[["customer.events<br/>CustomerCreated / CustomerUpdated / ConsentChanged"]]
        T2[["order.events<br/>OrderCreated / OrderCompleted / OrderReturned"]]
        T3[["service.events<br/>SupportCaseCreated / SupportCaseResolved"]]
        T4[["loyalty.events<br/>LoyaltyStatusChanged"]]
        T5[["insight.events<br/>ChurnRiskChanged"]]
        DLQ[["dead letter"]]
    end
    subgraph CON["Process APIs consume / idempotent"]
        DP["Data Platform Ingest"]
        RT["Retention Workflow"]
        MK["Marketing Activation"]
        CA["Service Desk Cache"]
    end

    CRM --> CS --> T1
    OMS --> OS --> T2
    SUP --> SS --> T3
    LOY --> LS --> T4
    T1 & T2 & T3 & T4 --> DP --> SF[("Snowflake")]
    SF --> T5 --> RT
    T1 --> MK
    T1 --> CA
    T3 --> RT
    DP -.poison / exhausted retries.-> DLQ
    RT -.-> DLQ
    DLQ --> TR["Triage / named duty / SLA"]

    style BUS stroke-dasharray: 5 5
    style CON stroke-dasharray: 5 5
```

## Envelope

```mermaid
classDiagram
    class EventEnvelope {
        +string eventId
        +string eventType
        +string eventVersion
        +datetime occurredAt
        +datetime publishedAt
        +string source
        +string correlationId "same id as the sync path"
        +string causationId "which event caused this one"
        +string partitionKey "customer business key"
        +string dataClassification "travels with the payload"
        +object data "small and stable, not the whole entity"
    }
```

## Consumer idempotency

```mermaid
flowchart LR
    E["Event"] --> D{"eventId seen<br/>within the TTL?"}
    D -->|yes| A["Ack, do nothing"]
    D -->|no| O{"occurredAt older than<br/>the stored version?"}
    O -->|yes| A2["Ack, reject as stale"]
    O -->|no| AP["Apply / store eventId"]
    AP --> A3["Ack"]
```

At-least-once delivery plus deduplication at the consumer. Exactly-once across a
bus and a warehouse is a distributed transaction wearing a disguise.

The stale-update rejection uses `occurredAt` and the tracked-attribute hash,
the same mechanism the SCD2 batch loader already uses. That is not a
coincidence: **an event consumer writing to an SCD2 table is the batch loader
with a different trigger.**
