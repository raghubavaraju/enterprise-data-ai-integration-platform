# 01 / Enterprise context

Who uses the platform, what it depends on, and where the boundary is.

```mermaid
flowchart TB
    subgraph People["People"]
        AG["Service desk agent"]
        MKT["Marketing analyst"]
        AN["Data analyst"]
        ST["Data steward"]
    end

    subgraph Apps["Consuming applications"]
        SDA["Service desk<br/>application"]
        MAP["Marketing<br/>activation"]
        BI["BI and notebooks"]
        PRT["Partner integration"]
    end

    subgraph Platform["Enterprise Data &amp; AI Integration Platform"]
        direction TB
        API["MuleSoft API layers<br/>experience / process / system"]
        EDP["Snowflake<br/>ACME_EDP"]
        AI["AI service<br/>grounded generation"]
        GOV["Governance<br/>dictionary / DQ / lineage"]
        API --- EDP
        API --- AI
        EDP --- AI
        EDP --- GOV
    end

    subgraph Sources["Source systems (owned elsewhere)"]
        CRM[("CRM")]
        ECM[("E-commerce")]
        ERP[("ERP")]
        OMS[("Order management")]
        SUP[("Customer support")]
        LOY[("Loyalty")]
        PIM[("Product catalogue")]
    end

    subgraph External["External services"]
        IDP["Identity provider<br/>OAuth 2.0"]
        LLM["Model provider<br/>Cortex in-account, or external"]
        OBS["Monitoring and<br/>log analytics"]
    end

    AG --> SDA
    MKT --> MAP
    AN --> BI
    ST --> GOV

    SDA --> API
    MAP --> API
    BI --> API
    PRT --> API

    API --> CRM
    API --> OMS
    API --> SUP
    API --> LOY
    API --> PIM
    ECM -.batch.-> EDP
    ERP -.batch.-> EDP
    CRM -.batch + CDC.-> EDP
    OMS -.-> EDP
    SUP -.-> EDP
    LOY -.-> EDP
    PIM -.-> EDP

    API -.validates tokens.-> IDP
    AI --> LLM
    Platform -.telemetry.-> OBS

    style Platform fill:#f4f8ff,stroke:#4a7ebb,stroke-width:2px
```

## What the platform is accountable for

| In scope | Out of scope |
|---|---|
| Integrating customer data across sources | Owning any source system's data |
| A governed unified customer view | Replacing the CRM or the OMS |
| Governed AI over that view | General-purpose chat over enterprise data |
| API contracts and their lifecycle | The consuming applications themselves |
| Data quality measurement and quarantine | Fixing defects at source, that is the domain owner's job |
| Recovery of the platform's own data | Source system disaster recovery |

The last row on each side is the one that gets argued about. The platform
*reports* a data quality defect and quarantines the row; the domain owner fixes
the source. A platform that quietly corrects its inputs teaches the organisation
that the source does not matter.
