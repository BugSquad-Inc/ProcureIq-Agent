"""
paypal_adapter.py — PayPal & Procurement API Tool Adapter.

Supports all 50 tools seeded in the Tool Registry:
  - Distinguishes read-only vs mutating write operations (`WRITE_TOOLS`) for HITL gating
  - Echoes extracted parameters (amount, recipient, IDs, period, vendor) into realistic responses
  - Uses PayPal OAuth2 sandbox API when `PAYPAL_CLIENT_ID` & `PAYPAL_CLIENT_SECRET` are set
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Set

import structlog

logger = structlog.get_logger("procureiq.paypal_adapter")

# Mutating operations that trigger Human-in-the-Loop confirmation before execution
WRITE_TOOLS: Set[str] = {
    "send_payment",
    "create_order",
    "capture_order",
    "refund_payment",
    "authorize_payment",
    "create_payout_batch",
    "create_subscription_plan",
    "cancel_subscription",
    "create_invoice",
    "send_invoice",
    "cancel_invoice",
    "remind_invoice",
    "record_invoice_payment",
    "flag_invoice_discrepancy",
    "create_product",
    "accept_dispute_claim",
    "provide_dispute_evidence",
    "escalate_dispute",
    "create_purchase_order",
    "approve_purchase_order",
    "cancel_purchase_order",
    "create_vendor",
    "submit_goods_receipt",
    "create_rfq",
}

ALL_SUPPORTED_TOOLS: Set[str] = WRITE_TOOLS | {
    "get_payment",
    "list_transactions",
    "get_balance",
    "get_payout_batch",
    "get_subscription",
    "get_invoice",
    "list_invoices",
    "generate_invoice_number",
    "list_products",
    "get_sales_report",
    "get_settlement_report",
    "get_revenue_breakdown",
    "export_transactions_csv",
    "get_budget_utilization",
    "list_webhook_events",
    "verify_webhook_signature",
    "get_dispute",
    "list_disputes",
    "get_dispute_messages",
    "get_identity_verification",
    "get_risk_assessment",
    "get_purchase_order",
    "list_purchase_orders",
    "get_vendor_profile",
    "list_vendors",
    "get_spend_by_vendor",
}


def is_write_tool(tool_name: str) -> bool:
    """Return True if executing `tool_name` modifies external/financial state."""
    return tool_name in WRITE_TOOLS


async def execute_paypal_tool(
    tool_name: str,
    user_message: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute any of the 50 PayPal/procurement tools.
    Uses live PayPal Sandbox API if credentials exist; otherwise returns
    parameter-aware deterministic demo responses.
    """
    if tool_name not in ALL_SUPPORTED_TOOLS:
        return {"error": f"Tool '{tool_name}' is not registered in the API adapter."}

    extracted = params or {}
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()

    if client_id and secret:
        return await _call_real_paypal(tool_name, extracted, client_id, secret)

    logger.info("paypal_demo_mode", tool=tool_name, params=extracted)
    return _mock_response(tool_name, extracted)


async def _call_real_paypal(
    tool_name: str,
    params: Dict[str, Any],
    client_id: str,
    secret: str,
) -> Dict[str, Any]:
    """Real PayPal Sandbox API OAuth2 integration skeleton."""
    import base64
    import httpx

    credentials = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            "https://api-m.sandbox.paypal.com/v1/oauth2/token",
            headers={"Authorization": f"Basic {credentials}"},
            data={"grant_type": "client_credentials"},
        )
        if token_resp.status_code != 200:
            raise RuntimeError(f"PayPal OAuth failed with HTTP {token_resp.status_code}")

    return {
        "tool": tool_name,
        "status": "sandbox_authenticated",
        "params": params,
        "message": f"Authenticated with PayPal Sandbox for '{tool_name}'.",
    }


def _mock_response(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Generate realistic, parameter-aware mock responses for all 50 tools."""
    amount = params.get("amount", "$500.00")
    recipient = params.get("recipient") or params.get("recipient_email") or "vendor@example.com"
    invoice_id = params.get("invoice_id", "INV-2026-0042")
    po_id = params.get("po_id", "PO-2026-0188")
    dispute_id = params.get("dispute_id", "PP-D-12345")
    user_id = params.get("user_id", "user_123")
    vendor = params.get("vendor") or params.get("vendor_id") or "Acme Corp"
    period = params.get("period", "last_month")

    specific_mocks: Dict[str, Dict[str, Any]] = {
        # Payments
        "send_payment": {
            "transaction_id": "TXN-88412",
            "status": "COMPLETED",
            "amount": amount,
            "recipient": recipient,
            "message": f"Payment of {amount} sent to {recipient}.",
        },
        "get_payment": {
            "payment_id": params.get("payment_id", "PAY-9876"),
            "status": "COMPLETED",
            "amount": amount,
            "recipient": recipient,
        },
        "list_transactions": {
            "transactions": [
                {"id": "TXN-001", "amount": "$1,200.00", "status": "COMPLETED", "date": "2026-11-01"},
                {"id": "TXN-002", "amount": "$850.00", "status": "COMPLETED", "date": "2026-11-05"},
                {"id": "TXN-003", "amount": "$320.00", "status": "PENDING", "date": "2026-11-10"},
            ],
            "total_count": 3,
        },
        "get_balance": {
            "currency": "USD",
            "available": "$124,500.00",
            "pending": "$3,890.00",
        },
        "create_order": {
            "order_id": "ORD-2026-7710",
            "status": "CREATED",
            "amount": amount,
        },
        "capture_order": {
            "order_id": params.get("order_id", "ORD-2026-7710"),
            "status": "COMPLETED",
            "captured_amount": amount,
        },
        "refund_payment": {
            "refund_id": "REF-55210",
            "capture_id": params.get("capture_id", "CAP-1001"),
            "status": "COMPLETED",
            "amount": amount,
            "message": f"Refund of {amount} processed.",
        },
        "authorize_payment": {
            "authorization_id": "AUTH-3091",
            "status": "AUTHORIZED",
            "amount": amount,
        },
        "create_payout_batch": {
            "payout_batch_id": "BATCH-2026-991",
            "batch_status": "PENDING",
            "recipient_count": 5,
            "total_amount": amount,
        },
        "get_payout_batch": {
            "payout_batch_id": params.get("payout_batch_id", "BATCH-2026-991"),
            "batch_status": "SUCCESS",
            "processed_items": 5,
        },
        "create_subscription_plan": {
            "plan_id": "PLAN-ENT-01",
            "status": "ACTIVE",
            "amount": amount,
        },
        "get_subscription": {
            "subscription_id": params.get("subscription_id", "SUB-402"),
            "status": "ACTIVE",
            "next_billing_date": "2026-12-01",
        },
        "cancel_subscription": {
            "subscription_id": params.get("subscription_id", "SUB-402"),
            "status": "CANCELLED",
        },
        # Invoicing
        "create_invoice": {
            "invoice_id": invoice_id,
            "status": "DRAFT",
            "amount": amount,
            "recipient": recipient,
            "due_date": "2026-12-15",
            "message": f"Draft invoice {invoice_id} created for {recipient} ({amount}).",
        },
        "send_invoice": {
            "invoice_id": invoice_id,
            "status": "SENT",
            "amount": amount,
            "recipient": recipient,
            "message": f"Invoice {invoice_id} ({amount}) sent to {recipient}.",
        },
        "get_invoice": {
            "invoice_id": invoice_id,
            "status": "SENT",
            "amount": amount,
            "recipient": recipient,
        },
        "list_invoices": {
            "invoices": [
                {"invoice_id": "INV-2026-0041", "status": "PAID", "amount": "$2,400.00"},
                {"invoice_id": "INV-2026-0042", "status": "SENT", "amount": "$500.00"},
            ],
            "total_count": 2,
        },
        "cancel_invoice": {"invoice_id": invoice_id, "status": "CANCELLED"},
        "remind_invoice": {
            "invoice_id": invoice_id,
            "reminder_sent": True,
            "recipient": recipient,
        },
        "generate_invoice_number": {"next_invoice_number": "INV-2026-0043"},
        "record_invoice_payment": {
            "invoice_id": invoice_id,
            "recorded_amount": amount,
            "status": "MARKED_AS_PAID",
        },
        "flag_invoice_discrepancy": {
            "flag_id": "DISC-901",
            "invoice_id": invoice_id,
            "po_id": po_id,
            "status": "UNDER_REVIEW",
        },
        "create_product": {"product_id": "PROD-301", "status": "ACTIVE"},
        "list_products": {
            "products": [
                {"id": "PROD-101", "name": "Enterprise Server Node"},
                {"id": "PROD-102", "name": "Annual Maintenance SLA"},
            ]
        },
        # Analytics
        "get_sales_report": {
            "period": period,
            "total_sales": "$48,320.00",
            "transaction_count": 142,
            "average_order_value": "$340.28",
            "top_category": "Enterprise Hardware & Cloud",
        },
        "get_settlement_report": {
            "period": period,
            "settled_volume": "$46,910.00",
            "settlement_batches": 14,
        },
        "get_revenue_breakdown": {
            "period": period,
            "breakdown": [
                {"category": "Hardware", "revenue": "$28,400.00"},
                {"category": "Services", "revenue": "$19,920.00"},
            ],
        },
        "export_transactions_csv": {
            "export_id": "EXP-2026-11",
            "status": "READY",
            "row_count": 142,
        },
        "get_budget_utilization": {
            "department": params.get("department", "IT Infrastructure"),
            "allocated": "$250,000.00",
            "spent_and_committed": "$178,500.00",
            "utilization_pct": 71.4,
        },
        "list_webhook_events": {
            "events": [
                {"id": "WH-901", "type": "PAYMENT.CAPTURE.COMPLETED"},
                {"id": "WH-902", "type": "INVOICING.INVOICE.PAID"},
            ]
        },
        "verify_webhook_signature": {"verification_status": "SUCCESS"},
        # Disputes
        "get_dispute": {
            "dispute_id": dispute_id,
            "status": "OPEN",
            "reason": "ITEM_NOT_RECEIVED",
            "amount": "$250.00",
            "buyer": user_id,
            "opened_date": "2026-11-05",
        },
        "list_disputes": {
            "disputes": [
                {"id": "PP-D-12345", "buyer": user_id, "status": "OPEN", "amount": "$250.00"},
                {"id": "PP-D-12344", "buyer": "user_456", "status": "RESOLVED", "amount": "$89.00"},
            ],
            "open_count": 1,
        },
        "accept_dispute_claim": {"dispute_id": dispute_id, "status": "RESOLVED_REFUNDED"},
        "provide_dispute_evidence": {"dispute_id": dispute_id, "status": "WAITING_FOR_BUYER_RESPONSE"},
        "escalate_dispute": {"dispute_id": dispute_id, "status": "UNDER_REVIEW"},
        "get_dispute_messages": {
            "dispute_id": dispute_id,
            "messages": [{"sender": user_id, "content": "Shipment tracking has not updated in 5 days."}],
        },
        "get_identity_verification": {"user_id": user_id, "kyc_status": "VERIFIED"},
        "get_risk_assessment": {"risk_score": 14, "risk_level": "LOW"},
        # Procurement
        "create_purchase_order": {
            "po_id": po_id,
            "vendor": vendor,
            "amount": amount,
            "status": "PENDING_APPROVAL",
            "message": f"Purchase order {po_id} created for {vendor} ({amount}).",
        },
        "approve_purchase_order": {
            "po_id": po_id,
            "status": "APPROVED",
            "message": f"Purchase order {po_id} approved for fulfillment.",
        },
        "get_purchase_order": {
            "po_id": po_id,
            "vendor": vendor,
            "amount": amount,
            "status": "APPROVED",
        },
        "list_purchase_orders": {
            "purchase_orders": [
                {"po_id": "PO-2026-0188", "vendor": "Acme Corp", "amount": "$45,000.00", "status": "APPROVED"},
                {"po_id": "PO-2026-0189", "vendor": "Global Freight Ltd", "amount": "$12,300.00", "status": "PENDING_APPROVAL"},
            ],
            "total_count": 2,
        },
        "cancel_purchase_order": {"po_id": po_id, "status": "CANCELLED"},
        "get_vendor_profile": {
            "vendor": vendor,
            "payment_terms": "Net 30",
            "rating": 4.8,
            "active_contracts": 3,
        },
        "list_vendors": {
            "vendors": [
                {"vendor_id": "VND-001", "name": "Acme Corp", "category": "Hardware"},
                {"vendor_id": "VND-002", "name": "Global Freight Ltd", "category": "Logistics"},
            ]
        },
        "create_vendor": {"vendor_id": "VND-099", "vendor": vendor, "status": "ONBOARDED"},
        "get_spend_by_vendor": {
            "period": period,
            "vendors": [
                {"vendor": "Acme Corp", "total_spend": "$118,400.00"},
                {"vendor": "Global Freight Ltd", "total_spend": "$42,900.00"},
            ],
        },
        "submit_goods_receipt": {"receipt_id": "GR-7741", "po_id": po_id, "status": "RECEIVED"},
        "create_rfq": {"rfq_id": "RFQ-2026-019", "status": "ISSUED", "suppliers_invited": 3},
    }

    return specific_mocks.get(
        tool_name,
        {"tool": tool_name, "status": "success", "params": params, "demo": True},
    )
