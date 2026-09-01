"""Stand-ins for Acme's source systems (CRM, OMS, Support, Loyalty, PIM).

These exist so the API-led chain can be exercised end to end on a laptop.  They
are deliberately *dumb*: they serve the sample dataset over REST with the kind
of quirks real source systems have - inconsistent field naming, no pagination
contract, source-specific status codes - because normalising those quirks is
precisely the job of the System API layer.
"""
