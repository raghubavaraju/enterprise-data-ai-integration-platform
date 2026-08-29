# 07 / CI/CD

```mermaid
flowchart LR
    C(["Commit / PR"]) --> P1

    subgraph P1["Fast gates / parallel / ~2 min"]
        Q["Code quality<br/>ruff / SQL conventions / Mule XML"]
        A["API contracts<br/>OAS + RAML governance"]
        S["Security<br/>bandit / gitleaks / pip-audit / no-credentials"]
    end

    subgraph P2["Test gates / ~4 min"]
        T["Unit / data / API<br/>coverage ≥ 75%"]
        E["AI evaluation<br/>groundedness / safety / consistency"]
    end

    subgraph P3["Slow gates"]
        I["Integration<br/>full stack + smoke test"]
        M["Mule build + MUnit<br/>coverage ≥ 80%<br/><i>needs Anypoint credentials</i>"]
    end

    subgraph P4["Package"]
        K["Container image + Trivy scan"]
    end

    subgraph P5["Deploy / manual, environment approval"]
        D1["system APIs"] --> D2["process APIs"] --> D3["experience APIs"]
        D3 --> H{"Health check"}
        H -->|fail| RB["Roll back to the<br/>previous Exchange artefact"]
        H -->|pass| OK(["Deployed"])
    end

    Q --> T & E
    Q & A --> M
    T --> I & K
    E --> K
    S --> K
    A --> K
    I & M & K --> P5
```

## Why this order

**Fast gates first, in parallel.** A developer who has mis-formatted a file
learns in 40 seconds, not after a 12-minute Mule build.

**Nothing that needs a cloud account is required for a green build on a pull
request.** A contributor without an Anypoint licence or a Snowflake account can
run and pass the entire suite. That is the difference between a repository people
contribute to and one they read.

**Deploy system → process → experience.** A process API calling a system API that
does not yet have its new endpoint fails; the reverse does not.

## The gates, and what each one refuses to let through

| Gate | Refuses |
|---|---|
| Code quality | Lint failures; `SELECT *` in a consumption view; an unqualified object in a portable script; a read of an SCD2 table without `IS_CURRENT`; malformed Mule XML |
| API contracts | A spec that breaks the governance rules, verbs in paths, no 401, an unbounded collection endpoint, a missing error model |
| Security | Any credential, private key or account identifier in the tree; a HIGH bandit finding |
| Tests | Coverage below 75%; a sample dataset that is out of date; any failing invariant |
| AI evaluation | Generation that is less grounded, less safe or less consistent than the thresholds |
| Integration | A break in the cross-process behaviour: correlation propagation, degradation, entitlement masking |
| Mule | A failing MUnit test, or flow coverage below 80% |
