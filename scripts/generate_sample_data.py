#!/usr/bin/env python3
"""
Generate the deterministic sample dataset for the Acme Retail POC.

Design notes
------------
* Seeded RNG -> the dataset is reproducible; regenerating it produces byte-identical
  files so diffs in git are meaningful.
* The dataset deliberately contains *data quality defects* (duplicate customers,
  malformed e-mail addresses, a null business key, a negative order amount,
  a future-dated order, an orphan order line).  The checks in
  ``snowflake/09-data-quality`` are expected to find exactly these rows -
  see ``snowflake/09-data-quality/expected-results.md``.
* All names, addresses and e-mail addresses are synthetic and use RFC 2606
  reserved domains (``example.com``).  No real personal data is present.

Usage:  python scripts/generate_sample_data.py [--out sample-data]
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SEED = 20260101
RUN_DATE = date(2026, 8, 1)          # "as of" date for the dataset
random.seed(SEED)

FIRST = ["Amara", "Liam", "Sofia", "Noah", "Priya", "Ethan", "Mei", "Lucas", "Aisha", "Diego",
         "Hana", "Oliver", "Zara", "Mateo", "Nina", "Ravi", "Elena", "Jonas", "Yuki", "Omar",
         "Clara", "Idris", "Marta", "Theo", "Nadia", "Felix", "Lina", "Arjun", "Freya", "Kofi"]
LAST = ["Okafor", "Bennett", "Rivera", "Hansen", "Nair", "Caldwell", "Chen", "Moreau", "Diallo",
        "Alvarez", "Sato", "Whitfield", "Haddad", "Rossi", "Kowalski", "Iyer", "Petrov", "Lindqvist",
        "Tanaka", "Farouk", "Novak", "Adeyemi", "Silva", "Berger", "Rahman", "Vogel", "Costa"]
CITIES = [("Omaha", "NE", "68102"), ("Austin", "TX", "73301"), ("Chicago", "IL", "60601"),
          ("Denver", "CO", "80202"), ("Seattle", "WA", "98101"), ("Atlanta", "GA", "30301"),
          ("Boston", "MA", "02108"), ("Phoenix", "AZ", "85001")]
CHANNELS = ["WEB", "MOBILE_APP", "STORE", "CALL_CENTER", "MARKETPLACE"]
CATEGORIES = ["Coffee", "Snacks", "Frozen", "Beverages", "Household", "Personal Care"]
SEGMENTS = ["CONSUMER", "SMALL_BUSINESS", "PREMIUM"]
TIERS = ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
CASE_TYPES = ["DELIVERY_ISSUE", "BILLING", "PRODUCT_QUALITY", "RETURN", "ACCOUNT", "GENERAL_ENQUIRY"]
PRIORITY = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
INTERACTION_TYPES = ["EMAIL_OPEN", "PROMO_CLICK", "APP_SESSION", "STORE_VISIT", "REVIEW_SUBMITTED",
                     "CART_ABANDONED", "NEWSLETTER_UNSUBSCRIBE"]

CASE_TEXT = {
    "DELIVERY_ISSUE": ["Order arrived two days late and the outer carton was crushed.",
                       "Courier marked the parcel delivered but nothing arrived at the address.",
                       "Delivery window was missed twice in the same week."],
    "BILLING": ["Charged twice for the same order on the same card.",
                "Promotional discount was not applied at checkout.",
                "Refund for the returned item has still not appeared."],
    "PRODUCT_QUALITY": ["The coffee beans tasted stale and the bag seal was already broken.",
                        "Frozen item arrived thawed and had to be discarded.",
                        "Packaging was damaged and the contents leaked."],
    "RETURN": ["Requesting a return label for an item that does not fit my machine.",
               "Return was collected three weeks ago and is still not processed."],
    "ACCOUNT": ["Cannot log in to the loyalty portal after the password reset.",
                "Loyalty points from the last two orders are missing from my balance."],
    "GENERAL_ENQUIRY": ["Do you plan to restock the seasonal blend?",
                        "Is the packaging on this product recyclable?"],
}
RESOLUTION_TEXT = ["Replacement dispatched at no cost and a goodwill credit applied.",
                   "Refund processed to the original payment method.",
                   "Explained the policy; customer accepted the outcome.",
                   "Escalated to the fulfilment partner; root cause corrected."]


def iso(dt: datetime | date) -> str:
    if isinstance(dt, datetime):
        return dt.replace(microsecond=0, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return dt.isoformat()


def build() -> dict:
    # ---------------------------------------------------------------- products
    products = []
    for i in range(1, 41):
        cat = CATEGORIES[i % len(CATEGORIES)]
        products.append({
            "productId": f"PRD-{i:04d}",
            "sku": f"ACME-{cat[:3].upper()}-{i:04d}",
            "productName": f"{cat} Item {i:02d}",
            "category": cat,
            "subCategory": f"{cat} - {'Premium' if i % 3 == 0 else 'Everyday'}",
            "brand": "Acme" if i % 4 else "Acme Reserve",
            "unitPrice": round(random.uniform(2.5, 48.0), 2),
            "currency": "USD",
            "isActive": i % 17 != 0,
            "launchDate": iso(date(2023, 1, 1) + timedelta(days=i * 11)),
        })

    # --------------------------------------------------------------- customers
    customers, addresses, contacts = [], [], []
    used = set()
    for i in range(1, 61):
        fn, ln = random.choice(FIRST), random.choice(LAST)
        while (fn, ln) in used:
            fn, ln = random.choice(FIRST), random.choice(LAST)
        used.add((fn, ln))
        cid = f"CRM-{100000 + i}"
        created = date(2021, 1, 1) + timedelta(days=random.randint(0, 1500))
        email = f"{fn.lower()}.{ln.lower()}@example.com"
        # DQ defect: two malformed e-mail addresses
        if i == 7:
            email = f"{fn.lower()}.{ln.lower()}@example"          # no TLD
        if i == 23:
            email = f"{fn.lower()}[at]example.com"                # no @
        customers.append({
            "customerId": cid,
            "sourceSystem": "CRM",
            "firstName": fn,
            "lastName": ln,
            "email": email,
            "phone": f"+1-402-555-{1000 + i:04d}",
            "birthDate": iso(date(1955 + (i % 45), 1 + (i % 12), 1 + (i % 27))),
            "customerSegment": SEGMENTS[i % len(SEGMENTS)],
            "marketingOptIn": i % 5 != 0,
            "preferredChannel": CHANNELS[i % len(CHANNELS)],
            "status": "ACTIVE" if i % 19 else "INACTIVE",
            "createdAt": iso(created),
            "updatedAt": iso(created + timedelta(days=random.randint(1, 400))),
        })
        city, st, zp = CITIES[i % len(CITIES)]
        addresses.append({
            "addressId": f"ADR-{i:05d}", "customerId": cid, "addressType": "BILLING",
            "line1": f"{100 + i * 3} Maple Street", "line2": None if i % 3 else f"Apt {i}",
            "city": city, "state": st, "postalCode": zp, "country": "US",
            "isPrimary": True, "validFrom": iso(created),
        })
        if i % 4 == 0:
            addresses.append({
                "addressId": f"ADR-{i:05d}-S", "customerId": cid, "addressType": "SHIPPING",
                "line1": f"{500 + i} Birch Avenue", "line2": None, "city": city, "state": st,
                "postalCode": zp, "country": "US", "isPrimary": False, "validFrom": iso(created),
            })
        contacts.append({"contactId": f"CTC-{i:05d}", "customerId": cid, "contactType": "EMAIL",
                         "contactValue": email, "isVerified": i % 6 != 0, "isPrimary": True})
        contacts.append({"contactId": f"CTC-{i:05d}-P", "customerId": cid, "contactType": "PHONE",
                         "contactValue": f"+1-402-555-{1000 + i:04d}", "isVerified": i % 3 != 0,
                         "isPrimary": False})

    # DQ defect: exact-key duplicate emitted by a source replay
    dup = dict(customers[4])
    dup["updatedAt"] = iso(RUN_DATE)
    customers.append(dup)
    # DQ defect: fuzzy duplicate (same person, different customerId, casing/whitespace noise)
    fuzzy = dict(customers[9])
    fuzzy.update({"customerId": "CRM-900001", "email": customers[9]["email"].upper(),
                  "firstName": customers[9]["firstName"] + " ", "createdAt": iso(RUN_DATE)})
    customers.append(fuzzy)
    # DQ defect: missing business key
    orphan = dict(customers[15])
    orphan.update({"customerId": None, "email": "no.key@example.com"})
    customers.append(orphan)

    active_ids = [c["customerId"] for c in customers[:60]]

    # ------------------------------------------------------------------ orders
    orders, order_items = [], []
    oi = 0
    for n, cid in enumerate(active_ids):
        # engagement profile drives order volume -> makes churn signal learnable
        profile = n % 5
        count = {0: 0, 1: 1, 2: 4, 3: 9, 4: 15}[profile]
        for _k in range(count):
            oi += 1
            days_ago = random.randint(5, 640) if profile < 3 else random.randint(2, 260)
            odate = RUN_DATE - timedelta(days=days_ago)
            oid = f"ORD-{200000 + oi}"
            lines, total = [], 0.0
            for li in range(random.randint(1, 4)):
                p = random.choice(products)
                qty = random.randint(1, 5)
                line_total = round(p["unitPrice"] * qty, 2)
                total += line_total
                lines.append({
                    "orderItemId": f"{oid}-{li + 1}", "orderId": oid, "productId": p["productId"],
                    "sku": p["sku"], "quantity": qty, "unitPrice": p["unitPrice"],
                    "lineAmount": line_total, "currency": "USD",
                })
            status = random.choices(["COMPLETED", "SHIPPED", "CANCELLED", "RETURNED"],
                                    weights=[78, 12, 6, 4])[0]
            orders.append({
                "orderId": oid, "customerId": cid, "orderDate": iso(odate),
                "orderStatus": status, "channel": random.choice(CHANNELS),
                "currency": "USD", "orderAmount": round(total, 2),
                "discountAmount": round(total * random.choice([0, 0, 0.05, 0.1]), 2),
                "shippingAmount": round(random.uniform(0, 9.99), 2),
                "createdAt": iso(datetime.combine(odate, datetime.min.time())),
                "updatedAt": iso(datetime.combine(odate + timedelta(days=2), datetime.min.time())),
            })
            order_items.extend(lines)

    # DQ defect: negative order amount
    orders.append({"orderId": "ORD-999001", "customerId": active_ids[3],
                   "orderDate": iso(RUN_DATE - timedelta(days=30)), "orderStatus": "COMPLETED",
                   "channel": "WEB", "currency": "USD", "orderAmount": -42.50,
                   "discountAmount": 0, "shippingAmount": 0,
                   "createdAt": iso(RUN_DATE - timedelta(days=30)), "updatedAt": iso(RUN_DATE)})
    # DQ defect: future-dated order
    orders.append({"orderId": "ORD-999002", "customerId": active_ids[6],
                   "orderDate": iso(RUN_DATE + timedelta(days=120)), "orderStatus": "COMPLETED",
                   "channel": "MOBILE_APP", "currency": "USD", "orderAmount": 88.00,
                   "discountAmount": 0, "shippingAmount": 4.99,
                   "createdAt": iso(RUN_DATE), "updatedAt": iso(RUN_DATE)})
    # DQ defect: order referencing a customer that does not exist (referential integrity)
    orders.append({"orderId": "ORD-999003", "customerId": "CRM-404404",
                   "orderDate": iso(RUN_DATE - timedelta(days=10)), "orderStatus": "COMPLETED",
                   "channel": "WEB", "currency": "USD", "orderAmount": 61.25,
                   "discountAmount": 0, "shippingAmount": 0,
                   "createdAt": iso(RUN_DATE), "updatedAt": iso(RUN_DATE)})
    # DQ defect: order line referencing a product that does not exist
    order_items.append({"orderItemId": "ORD-999003-1", "orderId": "ORD-999003",
                        "productId": "PRD-9999", "sku": "ACME-XXX-9999", "quantity": 1,
                        "unitPrice": 61.25, "lineAmount": 61.25, "currency": "USD"})

    # ------------------------------------------------------------ support cases
    cases = []
    ci = 0
    for _n, cid in enumerate(active_ids):
        for _ in range(random.randint(0, 4)):
            ci += 1
            ct = random.choice(CASE_TYPES)
            opened = RUN_DATE - timedelta(days=random.randint(1, 400))
            resolved_days = random.randint(0, 21)
            is_open = random.random() < 0.18
            csat = None if is_open else random.choices([1, 2, 3, 4, 5], weights=[8, 10, 18, 34, 30])[0]
            cases.append({
                "caseId": f"CAS-{300000 + ci}", "customerId": cid, "caseType": ct,
                "priority": random.choice(PRIORITY),
                "subject": ct.replace("_", " ").title(),
                "description": random.choice(CASE_TEXT[ct]),
                "status": "OPEN" if is_open else "RESOLVED",
                "channel": random.choice(["EMAIL", "PHONE", "CHAT", "WEB_FORM"]),
                "openedAt": iso(datetime.combine(opened, datetime.min.time())),
                "resolvedAt": None if is_open else iso(
                    datetime.combine(opened + timedelta(days=resolved_days), datetime.min.time())),
                "resolutionNotes": None if is_open else random.choice(RESOLUTION_TEXT),
                "csatScore": csat,
                "reopenCount": 0 if random.random() < 0.85 else random.randint(1, 2),
            })

    # ------------------------------------------------------------- interactions
    interactions = []
    ii = 0
    for cid in active_ids:
        for _ in range(random.randint(0, 12)):
            ii += 1
            interactions.append({
                "interactionId": f"INT-{400000 + ii}", "customerId": cid,
                "interactionType": random.choice(INTERACTION_TYPES),
                "channel": random.choice(CHANNELS),
                "interactionTs": iso(datetime.combine(
                    RUN_DATE - timedelta(days=random.randint(1, 365)), datetime.min.time())),
                "campaignId": random.choice([None, "CMP-SPRING-26", "CMP-LOYALTY-BOOST", "CMP-WINBACK"]),
            })

    # ------------------------------------------------------------------ loyalty
    loyalty = []
    for n, cid in enumerate(active_ids):
        enrolled = n % 6 != 0
        if not enrolled:
            continue
        tier = TIERS[min(3, n % 4)]
        earned = random.randint(1000, 90000)
        # Redeemed can never exceed earned - except for the one deliberate
        # violation planted below, which DQ-L-003 is expected to catch.
        redeemed = random.randint(0, earned)
        loyalty.append({
            "loyaltyAccountId": f"LOY-{500000 + n}", "customerId": cid,
            "tier": tier, "pointsBalance": min(earned - redeemed, random.randint(0, 24000)),
            "pointsEarnedLifetime": earned,
            "pointsRedeemedLifetime": redeemed,
            "enrolledAt": iso(date(2021, 6, 1) + timedelta(days=n * 9)),
            "lastActivityAt": iso(RUN_DATE - timedelta(days=random.randint(1, 500))),
            "status": "ACTIVE" if n % 11 else "SUSPENDED",
        })
    # DQ defect: redeemed points exceed points ever earned (DQ-L-003)
    if loyalty:
        loyalty[2]["pointsRedeemedLifetime"] = loyalty[2]["pointsEarnedLifetime"] + 5000

    return {"products": products, "customers": customers, "customer_addresses": addresses,
            "customer_contacts": contacts, "orders": orders, "order_items": order_items,
            "support_cases": cases, "customer_interactions": interactions, "loyalty": loyalty}


KB_ARTICLES = [
    ("KB-001", "Late or missing delivery", "Delivery",
     """Acme Retail dispatches most orders within one business day. Standard delivery is
2-5 business days; expedited delivery is 1-2 business days.

If a parcel is marked delivered but not received, ask the customer to check with
neighbours and the building reception first, then raise a carrier trace. A carrier
trace takes up to 3 business days.

If the trace fails, the customer is entitled to a free replacement or a full refund.
Agents may issue a goodwill credit of up to 15 USD without supervisor approval."""),
    ("KB-002", "Damaged or defective goods", "Product Quality",
     """Customers may report damaged or defective goods within 30 days of delivery.
Photographic evidence is requested but is not mandatory for orders under 50 USD.

Chilled and frozen items that arrive thawed are always replaced free of charge and
the customer is asked to dispose of the item rather than return it.

Repeat quality complaints on the same SKU within 30 days must be flagged to the
category manager so that the batch can be quarantined."""),
    ("KB-003", "Returns and refunds", "Returns",
     """Unopened goods may be returned within 30 days for a full refund. Opened
consumables may be returned within 14 days if the customer is dissatisfied.

Refunds are issued to the original payment method and take 3-5 business days to
appear. Loyalty points earned on a refunded order are reversed automatically.

Return labels are free for orders over 25 USD and for any return caused by an
Acme error."""),
    ("KB-004", "Duplicate or incorrect charges", "Billing",
     """A pending authorisation is not a charge. Authorisations drop off within
5 business days.

A genuine duplicate charge (two settled transactions with the same amount, card and
timestamp within 10 minutes) must be refunded immediately without requiring the
customer to return anything.

Promotional discounts that failed to apply are refunded as the difference; the order
is not cancelled and re-placed."""),
    ("KB-005", "Loyalty programme tiers and points", "Loyalty",
     """Tiers are Bronze, Silver, Gold and Platinum. Tier is recalculated monthly on
trailing 12-month spend: Silver at 500 USD, Gold at 1,500 USD, Platinum at 4,000 USD.

Points are earned at 1 point per USD, doubled for Gold and tripled for Platinum.
Points expire 24 months after they are earned.

Points missing from an order usually indicate the order was placed while logged out.
Agents can retro-credit points for orders placed in the last 90 days."""),
    ("KB-006", "Account access and password reset", "Account",
     """Password reset links are valid for 60 minutes and can only be used once.
If the customer does not receive the e-mail, verify the address on file, check that
the account is not suspended, and confirm the message was not classified as spam.

Never read a reset code back to a customer over the phone, and never confirm whether
an e-mail address is registered to an unauthenticated caller."""),
    ("KB-007", "Subscription and repeat orders", "Orders",
     """Repeat orders can be paused, skipped or cancelled at any time before the cut-off,
which is 48 hours before the scheduled dispatch date.

Price changes on a subscription are notified 14 days in advance. A customer who
cancels within 14 days of a price increase is entitled to the previous price for one
further delivery."""),
    ("KB-008", "Data privacy and customer data requests", "Privacy",
     """Customers may request a copy of their data or ask for their account to be deleted.
Requests are fulfilled within 30 days and must be routed to the privacy team; agents
must never export customer data themselves.

Deletion removes profile and contact data. Transactional records are retained in
pseudonymised form for 7 years to meet financial reporting obligations."""),
    ("KB-009", "Retention offers and win-back", "Retention",
     """A customer who has not ordered in 120 days is eligible for a win-back offer.
Approved offers are: 15% off the next order, free expedited delivery for 60 days, or
a double-points month.

Retention offers must not be stacked with an existing promotional code, and only one
retention offer may be active per customer per quarter."""),
    ("KB-010", "Escalation and complaint handling", "Service",
     """Escalate to a supervisor when: the case has been reopened twice, the customer
requests escalation explicitly, the disputed value exceeds 250 USD, or the customer
alleges a safety issue with a product.

Safety allegations must additionally be reported to Quality Assurance the same day.
Target response times: Critical 2 hours, High 8 hours, Medium 1 business day,
Low 3 business days."""),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="sample-data")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "knowledge-base").mkdir(parents=True, exist_ok=True)

    data = build()
    name_map = {
        "customers": "customers.json", "customer_addresses": "customer-addresses.json",
        "customer_contacts": "customer-contacts.json", "orders": "orders.json",
        "order_items": "order-items.json", "products": "products.json",
        "support_cases": "support-cases.json",
        "customer_interactions": "customer-interactions.json", "loyalty": "loyalty.json",
    }
    for key, fname in name_map.items():
        (out / fname).write_text(json.dumps(data[key], indent=2) + "\n")
        print(f"  {fname:32s} {len(data[key]):5d} records")

    for aid, title, cat, body in KB_ARTICLES:
        (out / "knowledge-base" / f"{aid.lower()}-{title.lower().replace(' ', '-')}.md").write_text(
            f"---\narticle_id: {aid}\ntitle: {title}\ncategory: {cat}\n"
            f"owner: Customer Service Operations\nlast_reviewed: 2026-06-30\n---\n\n"
            f"# {title}\n\n{body}\n")
    print(f"  knowledge-base/                  {len(KB_ARTICLES):5d} articles")


if __name__ == "__main__":
    main()
