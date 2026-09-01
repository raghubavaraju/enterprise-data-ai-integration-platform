"""Runnable behavioural stand-in for the MuleSoft runtime.

The Mule 4 applications in ``mule/`` are the real implementation of the API-led
layers.  They need Anypoint Studio or a Mule runtime licence to execute, which
would make this repository unrunnable for anyone reading it.

This package implements the *same three layers, the same contracts, the same
policies and the same error semantics* in Python so that the architecture can be
exercised end to end with `make up`:

    experience  (:8080)  client-shaped, aggregated, masked, cached
    process     (:8091)  orchestration, enrichment, business rules, fallbacks
    system      (:8092)  one system per source, source quirks normalised here

They are separate processes and talk over HTTP, so the correlation-id
propagation, retry, circuit-breaking and partial-failure behaviour described in
the docs are actually demonstrable rather than asserted.

Each module names the Mule file it mirrors, and `docs/architecture.md` carries
the full mapping.  Where the two differ, the Mule application is authoritative.
"""
