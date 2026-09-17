# 02 / API-led architecture

Every application, and the rule that governs each layer.

```mermaid
flowchart TB
    subgraph C["Consumers"]
        SDA["Service desk<br/>acme-servicedesk-client<br/><i>pii:read</i>"]
        PORT["Self-service portal<br/>acme-portal-client"]
        BATCH["Nightly extract<br/>acme-batch-client"]
        RO["Reporting<br/>acme-readonly-client"]
        STA["Store associate handheld<br/>acme-store-app-client"]
    end

    subgraph GW["Anypoint API Gateway"]
        POL["JWT validation / SLA rate limiting<br/>spike control / client id enforcement<br/>IP allow-list / header removal"]
    end

    subgraph EXP["Experience layer, one per consumer need"]
        CXA["<b>Customer Experience API</b><br/>shape / mask / client SLA"]
        AIA["<b>AI Insights API</b><br/>separate SLA, separate policies"]
        SAA["<b>Store Associate API</b><br/>added later, no change below this box"]
    end

    subgraph PRO["Process layer, business processes"]
        C360["<b>Customer 360 Process API</b><br/>orchestrate / degrade / enrich"]
        CIP["<b>Customer Intelligence Process API</b><br/>idempotency / bulkhead / no auto-retry"]
    end

    subgraph SYS["System layer, one per source"]
        SFA["<b>Snowflake Data System API</b><br/>the only path to the warehouse"]
        CRMA["CRM System API"]
        OMSA["Order System API"]
        SUPA["Support System API"]
        LOYA["Loyalty System API"]
        PIMA["Catalogue System API"]
    end

    subgraph BE["Backends"]
        SF[("Snowflake")]
        CRM[("CRM")]
        OMS[("OMS")]
        SUP[("Support")]
        LOY[("Loyalty")]
        PIM[("PIM")]
        AISVC["AI service"]
    end

    SDA --> POL
    PORT --> POL
    BATCH --> POL
    RO --> POL
    STA --> POL
    POL --> CXA
    POL --> AIA
    POL --> SAA

    CXA --> C360
    SAA --> C360
    AIA --> CIP
    C360 --> SFA
    C360 --> CRMA
    C360 --> OMSA
    C360 --> SUPA
    C360 --> LOYA
    CIP --> SFA
    CIP --> AISVC

    SFA --> SF
    CRMA --> CRM
    OMSA --> OMS
    SUPA --> SUP
    LOYA --> LOY
    PIMA --> PIM

    style EXP fill:#e8f0fe
    style PRO fill:#e6f4ea
    style SYS fill:#fef7e0
```

## The rule for each layer

| Layer | One reason to change | Must not contain | Checked by |
|---|---|---|---|
| Experience | A consumer's needs change | Orchestration, source knowledge | Review: a second outbound call means it belongs in the process layer |
| Process | The business process changes | Source field names, connection details | Review |
| System | A source system changes | Business logic, cross-source joins | Review: a join across two sources means it has become a process API |

## The claim this diagram makes

Replacing the CRM changes `CRM System API` and nothing else. The CRM's
`CustomerNumber` vocabulary exists in exactly one file:

```
mule/system-api/crm-system-api/src/main/resources/dw/crm-customer-to-canonical.dwl
```

Adding a consumer changes only the Experience layer. `Store Associate API` is
that claim exercised rather than illustrated: it is a later addition
(`mule/experience-api/src/main/mule/store-associate-experience-api.xml`) that
calls `C360` through the same `processApi` connection settings as
`Customer Experience API`, and nothing in `PRO`, `SYS` or `BE` above changed
to accommodate it - checked by
`tests/api/test_gateway_layers.py::test_both_experience_apis_reuse_the_same_process_endpoint`,
which asserts both experience APIs' calls land on the identical process path.
