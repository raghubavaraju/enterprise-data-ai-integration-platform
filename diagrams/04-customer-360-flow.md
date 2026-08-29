# 04 / Customer 360 data flow

From a record in a source system to a number on an agent's screen.

```mermaid
flowchart TB
    subgraph D1["Day 0 / source"]
        SRC["CRM record<br/>CustomerNumber CRM-100005<br/>SegmentCd PRM / OptInFlag Y"]
    end

    subgraph D2["Nightly / ingestion"]
        EXT["Incremental extract<br/>updatedSince = watermark"]
        LAND["RAW_CRM_CUSTOMER<br/>+ _BATCH_ID, _CORRELATION_ID<br/>+ SRC_PAYLOAD (schema evolution)"]
    end

    subgraph D3["Nightly / cleanse"]
        TYPE["TRY_CAST to typed columns"]
        VAL["Validate → DQ_STATUS + failed rules"]
        DED1["Dedupe exact: latest per business key"]
        DED2["Dedupe fuzzy: MATCH_KEY + survivorship"]
        STG["STG_CUSTOMER + _ROW_HASH"]
    end

    subgraph D4["Nightly / conform"]
        HASH{"Tracked-attribute<br/>hash changed?"}
        CLOSE["Close the open version<br/>VALID_TO = source update time"]
        OPEN["Insert a new open version<br/>VALID_TO = 9999-12-31"]
        SKIP["No change → no new version"]
    end

    subgraph D5["Nightly / aggregate"]
        OS["Order summary<br/>revenue = NET_AMOUNT where recognised"]
        SS["Support summary"]
        ES["Engagement summary<br/>ENGAGEMENT_SCORE defined here"]
        FS["Feature store<br/>point-in-time, versioned"]
        CS["Churn score + stored drivers"]
        C360["<b>CUSTOMER_360</b><br/>+ AS_OF_TIMESTAMP<br/>+ DATA_COMPLETENESS_SCORE<br/>+ CONTRIBUTING_SOURCES"]
    end

    subgraph D6["On request / serve"]
        SYS["Snowflake System API<br/>bind params / QUERY_TAG"]
        PROC["Process API<br/>concurrent reads / degrade on failure"]
        EXP["Experience API<br/>mask unless pii:read"]
        SCR["Agent's screen"]
    end

    SRC --> EXT --> LAND --> TYPE --> VAL --> DED1 --> DED2 --> STG --> HASH
    HASH -->|yes| CLOSE --> OPEN
    HASH -->|no| SKIP
    OPEN --> OS & SS & ES
    SKIP --> OS
    OS & SS & ES --> FS --> CS --> C360
    ES --> C360
    C360 --> SYS --> PROC --> EXP --> SCR
```

## What happens to each planted defect

```mermaid
flowchart LR
    subgraph In["Eight defects in sample-data/"]
        d1["null business key"]
        d2["negative order amount"]
        d3["future-dated order"]
        d4["2 malformed e-mails"]
        d5["exact duplicate"]
        d6["fuzzy duplicate"]
        d7["orphan order + line"]
        d8["loyalty inconsistency"]
    end
    d1 --> q["Quarantine<br/>RAW_REJECTED_RECORDS<br/><b>FAIL</b>"]
    d2 --> q
    d3 --> q
    d4 --> w["Load, flag, scorecard<br/><b>WARN</b>"]
    d6 --> sup["Suppress by survivorship<br/>+ record for a steward<br/><b>WARN</b>"]
    d7 --> w
    d8 --> w
    d5 --> sil["Collapse silently<br/><i>a source replay is not a defect</i>"]
```

Expected outcome on a fresh build: **14 PASS / 5 WARN / 3 FAIL**, asserted by
`tests/data/test_data_quality.py`.
