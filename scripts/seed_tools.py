"""
seed_tools.py — Seed the Tool Registry with 50 PayPal & procurement API tools.

Run with:
  python scripts/seed_tools.py             # inserts missing tools
  python scripts/seed_tools.py --refresh   # inserts + re-embeds existing tools
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

TOOLS = [
    # ── Payments (10) ────────────────────────────────────────────────────────
    {"name": "send_payment", "domain": "payments",
     "description": "Send a payment to a recipient's email or phone number via PayPal.",
     "schema": {"recipient": "string", "amount": "number", "currency": "string", "note": "string"},
     "endpoint": "/v1/payments/payment"},
    {"name": "get_payment", "domain": "payments",
     "description": "Retrieve details of a specific payment by payment ID.",
     "schema": {"payment_id": "string"},
     "endpoint": "/v1/payments/payment/{payment_id}"},
    {"name": "list_transactions", "domain": "payments",
     "description": "List recent payment transactions with optional date range filter.",
     "schema": {"start_date": "string", "end_date": "string", "page_size": "integer"},
     "endpoint": "/v1/reporting/transactions"},
    {"name": "get_balance", "domain": "payments",
     "description": "Get the current available and pending PayPal account balance.",
     "schema": {},
     "endpoint": "/v1/reporting/balances"},
    {"name": "create_order", "domain": "payments",
     "description": "Create a new PayPal order for checkout or B2B payment flow.",
     "schema": {"amount": "number", "currency": "string", "description": "string"},
     "endpoint": "/v2/checkout/orders"},
    {"name": "capture_order", "domain": "payments",
     "description": "Capture (complete) a previously approved PayPal order.",
     "schema": {"order_id": "string"},
     "endpoint": "/v2/checkout/orders/{order_id}/capture"},
    {"name": "refund_payment", "domain": "payments",
     "description": "Issue a full or partial refund for a completed payment.",
     "schema": {"capture_id": "string", "amount": "number", "reason": "string"},
     "endpoint": "/v2/payments/captures/{capture_id}/refund"},
    {"name": "authorize_payment", "domain": "payments",
     "description": "Place a temporary authorization hold on customer funds before capturing payment.",
     "schema": {"order_id": "string", "amount": "number", "currency": "string"},
     "endpoint": "/v2/checkout/orders/{order_id}/authorize"},
    {"name": "create_payout_batch", "domain": "payments",
     "description": "Send batch payouts to multiple vendors, suppliers, or contractors in one call.",
     "schema": {"items": "array", "email_subject": "string", "currency": "string"},
     "endpoint": "/v1/payments/payouts"},
    {"name": "get_payout_batch", "domain": "payments",
     "description": "Check the processing status and line items of a vendor payout batch.",
     "schema": {"payout_batch_id": "string"},
     "endpoint": "/v1/payments/payouts/{payout_batch_id}"},

    # ── Subscriptions & Plans (3, domain=payments) ───────────────────────────
    {"name": "create_subscription_plan", "domain": "payments",
     "description": "Create a recurring subscription billing plan.",
     "schema": {"name": "string", "billing_cycle": "string", "amount": "number"},
     "endpoint": "/v1/billing/plans"},
    {"name": "get_subscription", "domain": "payments",
     "description": "Get details of an active customer subscription.",
     "schema": {"subscription_id": "string"},
     "endpoint": "/v1/billing/subscriptions/{subscription_id}"},
    {"name": "cancel_subscription", "domain": "payments",
     "description": "Cancel an active customer subscription with optional reason.",
     "schema": {"subscription_id": "string", "reason": "string"},
     "endpoint": "/v1/billing/subscriptions/{subscription_id}/cancel"},

    # ── Invoicing & Catalog (11) ─────────────────────────────────────────────
    {"name": "create_invoice", "domain": "invoicing",
     "description": "Create a new draft invoice with line items and recipient details.",
     "schema": {"recipient_email": "string", "items": "array", "due_date": "string", "currency": "string"},
     "endpoint": "/v2/invoicing/invoices"},
    {"name": "send_invoice", "domain": "invoicing",
     "description": "Send a draft invoice to the recipient via email.",
     "schema": {"invoice_id": "string"},
     "endpoint": "/v2/invoicing/invoices/{invoice_id}/send"},
    {"name": "get_invoice", "domain": "invoicing",
     "description": "Retrieve details of a specific invoice by ID.",
     "schema": {"invoice_id": "string"},
     "endpoint": "/v2/invoicing/invoices/{invoice_id}"},
    {"name": "list_invoices", "domain": "invoicing",
     "description": "List all invoices with optional status and date filters.",
     "schema": {"status": "string", "start_date": "string", "end_date": "string"},
     "endpoint": "/v2/invoicing/invoices"},
    {"name": "cancel_invoice", "domain": "invoicing",
     "description": "Cancel a sent or draft invoice.",
     "schema": {"invoice_id": "string", "reason": "string"},
     "endpoint": "/v2/invoicing/invoices/{invoice_id}/cancel"},
    {"name": "remind_invoice", "domain": "invoicing",
     "description": "Send a reminder notification to a recipient about an unpaid invoice.",
     "schema": {"invoice_id": "string"},
     "endpoint": "/v2/invoicing/invoices/{invoice_id}/remind"},
    {"name": "generate_invoice_number", "domain": "invoicing",
     "description": "Generate the next available invoice number for use in a new invoice.",
     "schema": {},
     "endpoint": "/v2/invoicing/generate-next-invoice-number"},
    {"name": "record_invoice_payment", "domain": "invoicing",
     "description": "Record an external wire transfer or offline payment against an invoice.",
     "schema": {"invoice_id": "string", "amount": "number", "method": "string", "payment_date": "string"},
     "endpoint": "/v2/invoicing/invoices/{invoice_id}/payments"},
    {"name": "flag_invoice_discrepancy", "domain": "invoicing",
     "description": "Flag a price, tax, or quantity mismatch between a vendor invoice and purchase order.",
     "schema": {"invoice_id": "string", "po_id": "string", "reason": "string"},
     "endpoint": "/v1/invoicing/reconcile/flag"},
    {"name": "create_product", "domain": "invoicing",
     "description": "Create a product or service entry in the catalog for use in invoices.",
     "schema": {"name": "string", "description": "string", "type": "string", "category": "string"},
     "endpoint": "/v1/catalogs/products"},
    {"name": "list_products", "domain": "invoicing",
     "description": "List all products and services in the catalog.",
     "schema": {"page_size": "integer"},
     "endpoint": "/v1/catalogs/products"},

    # ── Analytics, Budgets & Webhooks (7) ────────────────────────────────────
    {"name": "get_sales_report", "domain": "analytics",
     "description": "Get a sales volume report for a specified time period with transaction totals.",
     "schema": {"period": "string", "start_date": "string", "end_date": "string"},
     "endpoint": "/v1/reporting/transactions"},
    {"name": "get_settlement_report", "domain": "analytics",
     "description": "Retrieve settlement batch reports showing cleared funds.",
     "schema": {"start_date": "string", "end_date": "string"},
     "endpoint": "/v1/reporting/dataset-download"},
    {"name": "get_revenue_breakdown", "domain": "analytics",
     "description": "Break down revenue by product category, region, or time period.",
     "schema": {"group_by": "string", "period": "string"},
     "endpoint": "/v1/reporting/revenue"},
    {"name": "export_transactions_csv", "domain": "analytics",
     "description": "Export all transactions for a date range as a CSV file.",
     "schema": {"start_date": "string", "end_date": "string"},
     "endpoint": "/v1/reporting/export"},
    {"name": "get_budget_utilization", "domain": "analytics",
     "description": "Track department budget utilization, committed purchase orders, and remaining spend.",
     "schema": {"department": "string", "fiscal_quarter": "string"},
     "endpoint": "/v1/analytics/budget-utilization"},
    {"name": "list_webhook_events", "domain": "analytics",
     "description": "List all recent webhook events fired by the payment system.",
     "schema": {"event_type": "string", "start_date": "string"},
     "endpoint": "/v1/notifications/webhooks-events"},
    {"name": "verify_webhook_signature", "domain": "analytics",
     "description": "Verify the authenticity of an incoming webhook payload signature.",
     "schema": {"transmission_id": "string", "transmission_sig": "string", "payload": "string"},
     "endpoint": "/v1/notifications/verify-webhook-signature"},

    # ── Disputes & Compliance (8) ────────────────────────────────────────────
    {"name": "get_dispute", "domain": "disputes",
     "description": "Retrieve details of a specific dispute or chargeback case.",
     "schema": {"dispute_id": "string"},
     "endpoint": "/v1/customer/disputes/{dispute_id}"},
    {"name": "list_disputes", "domain": "disputes",
     "description": "List all open and closed disputes with optional status filter.",
     "schema": {"status": "string", "dispute_state": "string"},
     "endpoint": "/v1/customer/disputes"},
    {"name": "accept_dispute_claim", "domain": "disputes",
     "description": "Accept a dispute claim and issue a refund to the buyer.",
     "schema": {"dispute_id": "string", "note": "string"},
     "endpoint": "/v1/customer/disputes/{dispute_id}/accept-claim"},
    {"name": "provide_dispute_evidence", "domain": "disputes",
     "description": "Upload evidence (documents, screenshots) to contest a dispute.",
     "schema": {"dispute_id": "string", "evidence_type": "string", "evidence": "string"},
     "endpoint": "/v1/customer/disputes/{dispute_id}/provide-evidence"},
    {"name": "escalate_dispute", "domain": "disputes",
     "description": "Escalate an open dispute to PayPal for mediation.",
     "schema": {"dispute_id": "string", "note": "string"},
     "endpoint": "/v1/customer/disputes/{dispute_id}/escalate"},
    {"name": "get_dispute_messages", "domain": "disputes",
     "description": "Retrieve the message thread between buyer and seller in a dispute.",
     "schema": {"dispute_id": "string"},
     "endpoint": "/v1/customer/disputes/{dispute_id}/messages"},
    {"name": "get_identity_verification", "domain": "disputes",
     "description": "Check identity verification status for a user or vendor.",
     "schema": {"user_id": "string"},
     "endpoint": "/v1/identity/verify"},
    {"name": "get_risk_assessment", "domain": "disputes",
     "description": "Get risk score and fraud signals for a transaction or user.",
     "schema": {"transaction_id": "string"},
     "endpoint": "/v1/risk/transaction-contexts"},

    # ── Procurement & Supply Chain (11) ──────────────────────────────────────
    {"name": "create_purchase_order", "domain": "procurement",
     "description": "Create a new purchase order for a vendor with line items and delivery terms.",
     "schema": {"vendor_id": "string", "items": "array", "delivery_date": "string", "total_amount": "number"},
     "endpoint": "/v1/procurement/purchase-orders"},
    {"name": "approve_purchase_order", "domain": "procurement",
     "description": "Approve a pending purchase order for payment processing.",
     "schema": {"po_id": "string", "approver_note": "string"},
     "endpoint": "/v1/procurement/purchase-orders/{po_id}/approve"},
    {"name": "get_purchase_order", "domain": "procurement",
     "description": "Retrieve details of a specific purchase order by ID.",
     "schema": {"po_id": "string"},
     "endpoint": "/v1/procurement/purchase-orders/{po_id}"},
    {"name": "list_purchase_orders", "domain": "procurement",
     "description": "List all purchase orders with optional status, vendor, and date filters.",
     "schema": {"status": "string", "vendor_id": "string"},
     "endpoint": "/v1/procurement/purchase-orders"},
    {"name": "cancel_purchase_order", "domain": "procurement",
     "description": "Cancel a pending or approved purchase order.",
     "schema": {"po_id": "string", "reason": "string"},
     "endpoint": "/v1/procurement/purchase-orders/{po_id}/cancel"},
    {"name": "get_vendor_profile", "domain": "procurement",
     "description": "Retrieve vendor profile including contact info, payment terms, and history.",
     "schema": {"vendor_id": "string"},
     "endpoint": "/v1/procurement/vendors/{vendor_id}"},
    {"name": "list_vendors", "domain": "procurement",
     "description": "List all registered vendors with optional category and status filters.",
     "schema": {"category": "string", "status": "string"},
     "endpoint": "/v1/procurement/vendors"},
    {"name": "create_vendor", "domain": "procurement",
     "description": "Register a new vendor in the procurement system.",
     "schema": {"name": "string", "email": "string", "payment_terms": "string", "category": "string"},
     "endpoint": "/v1/procurement/vendors"},
    {"name": "get_spend_by_vendor", "domain": "procurement",
     "description": "Get total spend broken down by vendor for a specified period.",
     "schema": {"period": "string", "category": "string"},
     "endpoint": "/v1/procurement/analytics/spend-by-vendor"},
    {"name": "submit_goods_receipt", "domain": "procurement",
     "description": "Record receipt of goods against a purchase order.",
     "schema": {"po_id": "string", "received_items": "array", "received_date": "string"},
     "endpoint": "/v1/procurement/goods-receipts"},
    {"name": "create_rfq", "domain": "procurement",
     "description": "Issue a Request for Quotation (RFQ) to shortlisted suppliers for competitive bidding.",
     "schema": {"suppliers": "array", "items": "array", "deadline": "string"},
     "endpoint": "/v1/procurement/rfqs"},
]


async def seed(overwrite_existing: bool = False):
    from sqlalchemy import text
    from app.infrastructure.database import models  # noqa: F401
    from app.infrastructure.database.session import AsyncSessionLocal, Base, engine
    from app.tools.registry import upsert_tools_batch

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        counts = await upsert_tools_batch(
            session=session,
            tools_data=TOOLS,
            overwrite_existing=overwrite_existing,
        )

    print(
        f"Seeded tools -> created={counts['created']}, "
        f"updated={counts['updated']}, skipped={counts['skipped']} "
        f"(total catalog={len(TOOLS)})."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed ProcureIQ Tool Registry")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-embed and update tools that already exist in the database.",
    )
    args = parser.parse_args()
    asyncio.run(seed(overwrite_existing=args.refresh))
