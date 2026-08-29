# 03 / Snowflake data architecture

```mermaid
flowchart TB
    subgraph ING["Ingestion"]
        ST["External stage<br/>versioned object store"]
        SP["Snowpipe<br/>continuous"]
        MB["Mule bulk / single record"]
    end

    subgraph RAW["RAW, immutable landing"]
        R1["RAW_CRM_CUSTOMER"]
        R2["RAW_OMS_ORDER"]
        R3["RAW_SUP_CASE"]
        R4["RAW_LOY_ACCOUNT"]
        R5["RAW_SUP_KNOWLEDGE_ARTICLE"]
        RJ["RAW_REJECTED_RECORDS<br/><i>quarantine, never deletion</i>"]
    end

    subgraph STG["STAGING, typed / cleansed / deduplicated"]
        S1["STG_CUSTOMER<br/>+ MATCH_KEY, DQ_STATUS"]
        S2["STG_SALES_ORDER"]
        S3["STG_SUPPORT_CASE"]
        S4["STG_LOYALTY_ACCOUNT"]
    end

    subgraph CORE["CORE: conformed enterprise entities"]
        C1["CUSTOMER<br/><b>SCD Type 2</b>"]
        C2["SALES_ORDER<br/>+ point-in-time CUSTOMER_SK"]
        C3["SALES_ORDER_ITEM"]
        C4["SUPPORT_CASE"]
        C5["LOYALTY_ACCOUNT"]
        C6["PRODUCT"]
        C7["CUSTOMER_INTERACTION"]
    end

    subgraph AN["ANALYTICS"]
        A1["CUSTOMER_ORDER_SUMMARY"]
        A2["CUSTOMER_SUPPORT_SUMMARY"]
        A3["CUSTOMER_ENGAGEMENT_SUMMARY<br/><i>defines ENGAGEMENT_SCORE once</i>"]
        A4["<b>CUSTOMER_360</b>"]
    end

    subgraph AI["AI"]
        I1["CUSTOMER_FEATURES<br/>point-in-time, versioned"]
        I2["CUSTOMER_CHURN_SCORE<br/>+ stored drivers"]
        I3["AI_CUSTOMER_INSIGHTS<br/>+ grounding snapshot"]
        I4["KB_DOCUMENT / KB_CHUNK<br/>VECTOR(FLOAT, 768)"]
        I5["AI_REQUEST_AUDIT<br/>AI_EVALUATION_RESULT"]
    end

    subgraph GOV["GOVERNANCE"]
        G1["DATA_DICTIONARY"]
        G2["DQ_RULE / DQ_RESULT"]
        G3["LINEAGE_EDGE"]
        G4["PIPELINE_RUN_LOG"]
        G5["INGESTION_WATERMARK"]
    end

    ST --> SP --> RAW
    MB --> RAW
    RAW --> STG
    STG -.fails BLOCKING.-> RJ
    STG --> CORE
    CORE --> A1 & A2 & A3
    A1 & A2 & A3 --> I1 --> I2 --> A4
    A3 --> A4
    C1 --> A4
    A4 --> I3
    R5 --> I4
    STG -.results.-> G2
    CORE -.results.-> G2

    style RAW fill:#fce8e6
    style STG fill:#fef7e0
    style CORE fill:#e6f4ea
    style AN fill:#e8f0fe
    style AI fill:#f3e8fd
```

## Build order, and why it is not alphabetical

There is a genuine dependency cycle to break: `CUSTOMER_360` wants the churn
probability for predicted CLV; churn scoring wants the feature store; the feature
store wants the ANALYTICS aggregates.

```mermaid
flowchart LR
    T1["06 / RAW → STAGING"] --> T2["06 / STAGING → CORE (SCD2)"]
    T2 --> T3["07-01 / order summary"]
    T2 --> T4["07-02 / support + engagement<br/>defines ENGAGEMENT_SCORE"]
    T3 --> T4
    T3 & T4 --> T5["08-01 / feature store"]
    T5 --> T6["08-02 / churn scoring"]
    T6 --> T7["07-03 / CUSTOMER_360"]
    T7 --> T8["09 / data quality"]
    T8 --> T9["RAG corpus refresh"]
```

The same ordering is a task DAG in Snowflake and an explicit list in
`local_warehouse/build.py`.
