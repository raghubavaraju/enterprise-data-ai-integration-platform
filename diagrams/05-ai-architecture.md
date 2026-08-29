# 05 / AI architecture

```mermaid
flowchart TB
    subgraph OPS["Operational systems"]
        CRM[("CRM")]
        OMS[("Orders")]
        SUP[("Support")]
    end

    subgraph SF["Snowflake"]
        C360["ANALYTICS.CUSTOMER_360"]
        V1["AI.V_CUSTOMER_AI_CONTEXT<br/><b>no name / no e-mail<br/>no phone / no date of birth</b>"]
        V2["AI.V_CUSTOMER_SUPPORT_CONTEXT<br/>truncated / redacted"]
        KB["AI.KB_CHUNK<br/>embedded corpus"]
        AUD[("AI_REQUEST_AUDIT<br/>AI_CUSTOMER_INSIGHTS<br/>AI_EVALUATION_RESULT")]
    end

    subgraph SVC["AI service"]
        G["1 / Assemble grounding<br/>via the data platform API"]
        S["2 / Redact + detect injection"]
        P["3 / Render versioned prompt<br/>explicit FACTS block"]
        R["Vector search<br/>top-k above a similarity floor"]
        M["4 / Model provider"]
        GR["5 / Output guardrails<br/>numbers / PII / commitments / action list"]
        EV["6 / Evaluate → confidence → review routing"]
        PER["7 / Persist with provenance"]
    end

    OPS --> C360 --> V1
    SUP --> V2
    C360 -.->|"no path exists"| SVC
    V1 --> G
    V2 --> G
    G --> S --> P
    P -->|NEXT_BEST_ACTION<br/>GROUNDED_QA| R
    KB --> R
    R --> M
    P --> M
    M --> GR
    GR -->|pass| EV
    GR -->|fail| DEG["Deterministic degraded message<br/><i>never returned as if it succeeded</i>"]
    EV --> PER --> AUD
    DEG --> PER
    EV --> OUT["Insight + confidence<br/>+ review status + citations"]

    style V1 fill:#e6f4ea,stroke:#137333,stroke-width:2px
    style GR fill:#fef7e0,stroke:#b06000,stroke-width:2px
```

## Human-in-the-loop routing

```mermaid
flowchart TB
    O["Generated output"] --> G{"Guardrails<br/>passed?"}
    G -->|no| HR["PENDING_REVIEW"]
    G -->|yes| I{"Injection detected<br/>in source data?"}
    I -->|yes| HR
    I -->|no| N{"Capability is<br/>NEXT_BEST_ACTION?"}
    N -->|yes| HR
    N -->|no| C{"Confidence ≥<br/>threshold?"}
    C -->|no| HR
    C -->|yes| AA["AUTO_APPROVED"]
    HR --> Q["Review queue<br/><i>monitored for depth and age</i>"]
```

Everything else is auto-approved, deliberately: **a review queue nobody reads is
worse than no queue**, because it manufactures the appearance of oversight.

## RAG, and why the similarity floor matters

```mermaid
flowchart LR
    Q["Question"] --> E["Embed"]
    E --> S["Vector search<br/><b>in the warehouse</b>"]
    KB[("KB_CHUNK")] --> S
    S --> F{"Any chunk above<br/>the similarity floor?"}
    F -->|yes| CTX["Context + article ids"] --> L["LLM"] --> A["Answer with [KB-xxx] citations"]
    F -->|no| N["'The knowledge base does not cover this.'"]
```

Without the floor, top-k always returns k chunks, so a question the knowledge
base does not cover still gets three confident-looking extracts and the model
answers from them. The floor makes "I don't know" reachable, and it is
tested.
