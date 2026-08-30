"""Load the sample dataset into the RAW layer.

This is the local stand-in for ingestion.  In cloud mode the same rows arrive
either through Snowpipe from an external stage (bulk/CDC) or through the
MuleSoft Snowflake System API (event-driven single records).  What matters is
that the *shape* is identical: source columns as text, plus the audit columns
(`_SRC_SYSTEM`, `_BATCH_ID`, `_CORRELATION_ID`, `_INGESTED_AT`, `_ROW_HASH`)
that make a row traceable back to the call that produced it.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from .warehouse import repo_root, shared

# raw table -> (sample file, source system, column mapping camelCase -> RAW column)
MAPPING: dict[str, tuple[str, str, dict[str, str]]] = {
    "RAW_CRM_CUSTOMER": ("customers.json", "CRM", {
        "customerId": "CUSTOMER_ID", "sourceSystem": "SOURCE_SYSTEM", "firstName": "FIRST_NAME",
        "lastName": "LAST_NAME", "email": "EMAIL", "phone": "PHONE", "birthDate": "BIRTH_DATE",
        "customerSegment": "CUSTOMER_SEGMENT", "marketingOptIn": "MARKETING_OPT_IN",
        "preferredChannel": "PREFERRED_CHANNEL", "status": "STATUS",
        "createdAt": "CREATED_AT", "updatedAt": "UPDATED_AT"}),
    "RAW_CRM_CUSTOMER_ADDRESS": ("customer-addresses.json", "CRM", {
        "addressId": "ADDRESS_ID", "customerId": "CUSTOMER_ID", "addressType": "ADDRESS_TYPE",
        "line1": "LINE1", "line2": "LINE2", "city": "CITY", "state": "STATE",
        "postalCode": "POSTAL_CODE", "country": "COUNTRY", "isPrimary": "IS_PRIMARY",
        "validFrom": "VALID_FROM"}),
    "RAW_CRM_CUSTOMER_CONTACT": ("customer-contacts.json", "CRM", {
        "contactId": "CONTACT_ID", "customerId": "CUSTOMER_ID", "contactType": "CONTACT_TYPE",
        "contactValue": "CONTACT_VALUE", "isVerified": "IS_VERIFIED", "isPrimary": "IS_PRIMARY"}),
    "RAW_CRM_INTERACTION": ("customer-interactions.json", "CRM", {
        "interactionId": "INTERACTION_ID", "customerId": "CUSTOMER_ID",
        "interactionType": "INTERACTION_TYPE", "channel": "CHANNEL",
        "interactionTs": "INTERACTION_TS", "campaignId": "CAMPAIGN_ID"}),
    "RAW_OMS_ORDER": ("orders.json", "OMS", {
        "orderId": "ORDER_ID", "customerId": "CUSTOMER_ID", "orderDate": "ORDER_DATE",
        "orderStatus": "ORDER_STATUS", "channel": "CHANNEL", "currency": "CURRENCY",
        "orderAmount": "ORDER_AMOUNT", "discountAmount": "DISCOUNT_AMOUNT",
        "shippingAmount": "SHIPPING_AMOUNT", "createdAt": "CREATED_AT",
        "updatedAt": "UPDATED_AT"}),
    "RAW_OMS_ORDER_ITEM": ("order-items.json", "OMS", {
        "orderItemId": "ORDER_ITEM_ID", "orderId": "ORDER_ID", "productId": "PRODUCT_ID",
        "sku": "SKU", "quantity": "QUANTITY", "unitPrice": "UNIT_PRICE",
        "lineAmount": "LINE_AMOUNT", "currency": "CURRENCY"}),
    "RAW_PIM_PRODUCT": ("products.json", "PIM", {
        "productId": "PRODUCT_ID", "sku": "SKU", "productName": "PRODUCT_NAME",
        "category": "CATEGORY", "subCategory": "SUB_CATEGORY", "brand": "BRAND",
        "unitPrice": "UNIT_PRICE", "currency": "CURRENCY", "isActive": "IS_ACTIVE",
        "launchDate": "LAUNCH_DATE"}),
    "RAW_SUP_CASE": ("support-cases.json", "SUPPORT", {
        "caseId": "CASE_ID", "customerId": "CUSTOMER_ID", "caseType": "CASE_TYPE",
        "priority": "PRIORITY", "subject": "SUBJECT", "description": "DESCRIPTION",
        "status": "STATUS", "channel": "CHANNEL", "openedAt": "OPENED_AT",
        "resolvedAt": "RESOLVED_AT", "resolutionNotes": "RESOLUTION_NOTES",
        "csatScore": "CSAT_SCORE", "reopenCount": "REOPEN_COUNT"}),
    "RAW_LOY_ACCOUNT": ("loyalty.json", "LOYALTY", {
        "loyaltyAccountId": "LOYALTY_ACCOUNT_ID", "customerId": "CUSTOMER_ID", "tier": "TIER",
        "pointsBalance": "POINTS_BALANCE", "pointsEarnedLifetime": "POINTS_EARNED_LIFETIME",
        "pointsRedeemedLifetime": "POINTS_REDEEMED_LIFETIME", "enrolledAt": "ENROLLED_AT",
        "lastActivityAt": "LAST_ACTIVITY_AT", "status": "STATUS"}),
}


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_raw(batch_id: str | None = None, correlation_id: str | None = None) -> dict[str, int]:
    con = shared()
    batch_id = batch_id or f"batch-{uuid.uuid4().hex[:12]}"
    correlation_id = correlation_id or f"acme-{uuid.uuid4()}"
    ingested_at = datetime.now(UTC).replace(tzinfo=None)
    data_dir = repo_root() / "sample-data"
    counts: dict[str, int] = {}

    for table, (fname, src, mapping) in MAPPING.items():
        records = json.loads((data_dir / fname).read_text())
        cols = list(mapping.values()) + ["SRC_PAYLOAD", "_SRC_SYSTEM", "_SRC_FILE",
                                         "_INGESTED_AT", "_BATCH_ID", "_CORRELATION_ID",
                                         "_ROW_HASH"]
        rows = []
        for rec in records:
            payload = json.dumps(rec, sort_keys=True)
            values = [_text(rec.get(k)) for k in mapping]
            values += [payload, src, f"sample-data/{fname}", ingested_at, batch_id,
                       correlation_id, hashlib.md5(payload.encode(), usedforsecurity=False).hexdigest()]
            rows.append(values)
        # noqa: S608 - `table` is a key of MAPPING, a literal in this module;
        # the row values are always bound, never interpolated.
        con.execute(f"DELETE FROM ACME_EDP.RAW.{table}")  # noqa: S608
        placeholders = ", ".join("?" for _ in cols)
        con.executemany(
            f"INSERT INTO ACME_EDP.RAW.{table} ({', '.join(cols)}) "  # noqa: S608
            f"VALUES ({placeholders})", rows)
        counts[table] = len(rows)

    # Knowledge base articles land in RAW too, so the RAG corpus has the same
    # provenance guarantees as structured data.
    kb_rows = []
    for path in sorted((data_dir / "knowledge-base").glob("*.md")):
        raw = path.read_text()
        meta, body = {}, raw
        if raw.startswith("---"):
            _, fm, body = raw.split("---", 2)
            for line in fm.strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        payload = json.dumps({"file": path.name, **meta}, sort_keys=True)
        kb_rows.append([meta.get("article_id", path.stem), meta.get("title"),
                        meta.get("category"), meta.get("owner"), meta.get("last_reviewed"),
                        f"kb://support/{path.name}", body.strip(), payload, "SUPPORT",
                        f"sample-data/knowledge-base/{path.name}", ingested_at, batch_id,
                        correlation_id, hashlib.md5(body.encode(), usedforsecurity=False).hexdigest()])
    con.execute("DELETE FROM ACME_EDP.RAW.RAW_SUP_KNOWLEDGE_ARTICLE")
    con.executemany(
        "INSERT INTO ACME_EDP.RAW.RAW_SUP_KNOWLEDGE_ARTICLE (ARTICLE_ID, TITLE, CATEGORY, OWNER,"
        " LAST_REVIEWED, SOURCE_URI, CONTENT, SRC_PAYLOAD, _SRC_SYSTEM, _SRC_FILE, _INGESTED_AT,"
        " _BATCH_ID, _CORRELATION_ID, _ROW_HASH) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", kb_rows)
    counts["RAW_SUP_KNOWLEDGE_ARTICLE"] = len(kb_rows)
    return counts
