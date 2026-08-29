# 06 / Security architecture

```mermaid
flowchart TB
    I["Internet"]

    subgraph TB1["Trust boundary 1 / public edge"]
        WAF["WAF<br/>TLS 1.2+ / DDoS / OWASP"]
        GW["API Gateway<br/>JWT / SLA rate limit / spike control<br/>client id / header removal"]
    end

    subgraph TB2["Trust boundary 2 / application VPC"]
        EXP["Experience APIs<br/>scope check / entitlement masking"]
        PRO["Process APIs<br/>private / mTLS / IP allow-list"]
        SYS["System APIs<br/>private / mTLS / no SQL accepted"]
        AIS["AI service<br/>PII-free grounding / guardrails"]
    end

    subgraph TB3["Trust boundary 3 / data platform"]
        SF["Snowflake<br/>network policy / key-pair JWT<br/>read-only role / masking + row access"]
    end

    subgraph TB4["Trust boundary 4 / external"]
        SRC["Source systems"]
        LLM["External model provider<br/><i>avoided when Cortex is used</i>"]
    end

    I --> WAF --> GW --> EXP --> PRO
    PRO --> SYS --> SF
    PRO --> AIS --> SF
    AIS -.only when not Cortex.-> LLM
    SYS --> SRC

    style TB1 stroke:#c5221f,stroke-width:2px,stroke-dasharray: 5 5
    style TB2 stroke:#c5221f,stroke-width:2px,stroke-dasharray: 5 5
    style TB3 stroke:#c5221f,stroke-width:2px,stroke-dasharray: 5 5
    style TB4 stroke:#c5221f,stroke-width:2px,stroke-dasharray: 5 5
```

## Identity and entitlement

```mermaid
flowchart LR
    subgraph Clients
        SD["acme-servicedesk-client<br/>customer / insights / ai:invoke / <b>pii:read</b>"]
        PT["acme-portal-client<br/>customer / insights / ai:invoke"]
        BA["acme-batch-client<br/>customer / insights"]
        RO["acme-readonly-client<br/>customer"]
        AIC["acme-ai-service<br/>customer / insights / ai:invoke / <b>ai:write</b>"]
    end
    subgraph Snowflake roles
        RORO["ACME_INTEGRATION_RO<br/>SELECT on views only"]
        AIR["ACME_AI_SERVICE<br/>AI-safe views + 3 named writes"]
        AN["ACME_ANALYST<br/>views, masked"]
        DE["ACME_DATA_ENGINEER<br/>owns the pipeline"]
    end
    SD & PT & BA & RO --> API["Platform identity"] --> RORO
    AIC --> AIR
```

Exactly one client holds `pii:read` and exactly one holds `ai:write`. That is
what makes an access review a one-row answer instead of an investigation.

## The PII journey

```mermaid
flowchart LR
    S["Source: full PII"] --> R["RAW: full PII<br/>encrypted at rest"]
    R --> C["CORE: full PII<br/>+ masking policies"]
    C --> V1["Consumption view<br/>masked by role"]
    C --> V2["AI-safe view<br/><b>identifiers absent by construction</b>"]
    V1 --> API["API"] --> M{"Token has<br/>pii:read?"}
    M -->|yes| U["Unmasked"]
    M -->|no| MK["Masked"]
    V2 --> AI["AI service"] --> RED["Free text redacted"] --> LLM["Model"]
    LLM --> OG{"Output guardrail:<br/>any identifier present?"}
    OG -->|yes| BLK["Blocked + audited"]
    OG -->|no| OK["Returned"]
```

The AI-safe view does not *filter* identifiers, it never selects them. No code
path can leak one by omitting a filter, because there is no filter to omit.
