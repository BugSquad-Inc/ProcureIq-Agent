"""
generate_enterprise_docs.py — Generate 42+ rich, domain-aligned enterprise FinTech &
Procurement documents inside `sample_docs/` (bringing total docs from 12 to 54+).

Covers all 9 ProcureIQ agent domains across .txt, .md, .pdf, and .docx formats:
  - Invoicing (8 docs)
  - Procurement POs, RFQs & Goods Receipts (8 docs)
  - Vendor Master Profiles & Tier Matrix (6 docs)
  - Payments, Authorizations, Captures, Payouts & Subscriptions (8 docs)
  - Disputes, KYC & Fraud Risk Assessments (6 docs)
  - Analytics, Budgets, Settlements, Webhooks & FinTech Compliance (6 docs)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import fitz  # pymupdf
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "sample_docs"


def write_txt_or_md(filename: str, content: str) -> None:
    (OUT_DIR / filename).write_text(content.strip() + "\n", encoding="utf-8")


def write_pdf(filename: str, title: str, body: str) -> None:
    doc = fitz.open()
    lines = [title, "=" * len(title), ""] + body.strip().splitlines()
    page = doc.new_page(width=612, height=792)
    y = 54
    for line in lines:
        if y > 740:
            page = doc.new_page(width=612, height=792)
            y = 54
        fontsize = 13 if line == title else 10
        page.insert_text((48, y), line, fontsize=fontsize, fontname="helv")
        y += 16 if line.strip() else 10
    doc.save(str(OUT_DIR / filename))
    doc.close()


def write_docx(filename: str, title: str, body: str) -> None:
    doc = Document()
    doc.add_heading(title, level=1)
    for para in body.strip().split("\n\n"):
        doc.add_paragraph(para.strip())
    doc.save(str(OUT_DIR / filename))


TEXT_DOCS: Dict[str, str] = {
    # ── 1. Invoicing (7 .txt/.md + 1 .pdf below = 8) ─────────────────────────
    "invoice_004_emma.txt": """
INVOICE RECORD: INVOICE_004 (INV-2026-004)
==========================================
Invoice ID: INVOICE_004
Reference PO: PO-2026-0302
Status: OVERDUE (Past Due by 9 Days)
Issue Date: 2026-10-12
Due Date: 2026-11-02

Bill To:
  Recipient: Emma Watson <emma@cloudscale.io>
  Company: CloudScale Infrastructure Inc.
  Billing Contact: emma@cloudscale.io

Line Items:
  1. Reserved H100 Cluster Burst Capacity (480 hrs) ....... $3,200.00
  2. High-Throughput Egress Storage Add-on ................ $650.00

Subtotal: $3,850.00
Tax: $0.00 (Reseller Exemption #CA-9981)
Total Amount Due: $3,850.00
Payment Terms: Net 21

Notes: Send polite payment reminder via remind_invoice to emma@cloudscale.io referencing PO-2026-0302.
""",
    "invoice_005_david.txt": """
INVOICE RECORD: INVOICE_005 (INV-2026-005)
==========================================
Invoice ID: INVOICE_005
Reference PO: PO-2026-0303
Status: PARTIALLY PAID — Wire Settlement Pending Posting
Issue Date: 2026-10-18
Due Date: 2026-11-18

Bill To:
  Recipient: David Kim <david.kim@quantledger.ai>
  Company: QuantLedger Financial Feeds
  Billing Contact: david.kim@quantledger.ai

Line Items:
  1. Level-2 Equities & Options Tick Stream ............... $1,120.00
  2. Historical Normalized CSV Backfill ................... $300.00

Total Amount Due: $1,420.00
Wire Confirmation Ref: WIRE-QL-88120
Notes: Record offline wire payment via record_invoice_payment for INVOICE_005 ($1,420.00).
""",
    "invoice_006_priya.txt": """
INVOICE RECORD: INVOICE_006 (INV-2026-006)
==========================================
Invoice ID: INVOICE_006
Reference PO: PO-2026-0304
Status: OVERDUE (15 Days Past Due — Escalation Notice Eligible)
Issue Date: 2026-10-01
Due Date: 2026-10-27

Bill To:
  Recipient: Priya Nair <priya@vertexsystems.io>
  Company: Vertex Security Group
  Billing Contact: priya@vertexsystems.io

Line Items:
  1. Enterprise Kubernetes Runtime Audit .................. $4,500.00
  2. SOC2 Evidence Automation Collector ................... $1,700.00

Total Amount Due: $6,200.00
Payment Terms: Net 26
Notes: Issue overdue invoice reminder for INVOICE_006 to Priya Nair (priya@vertexsystems.io).
""",
    "invoice_007_carlos.txt": """
INVOICE RECORD: INVOICE_007 (INV-2026-007)
==========================================
Invoice ID: INVOICE_007
Reference PO: PO-2026-0188
Status: DISCREPANCY HOLD — Amount Variance Exceeds 2% Threshold
Issue Date: 2026-11-04
Due Date: 2026-12-04

Bill To:
  Recipient: Carlos Mendez <carlos@meridianlogistics.com>
  Company: Meridian Global Freight
  Billing Contact: carlos@meridianlogistics.com

Billed Line Items:
  1. Cold-Chain Server Rack Transport ..................... $1,550.00
  2. Unapproved Peak-Season Fuel Surcharge ................ $400.00

Total Amount Billed: $1,950.00
Approved PO Freight Ceiling: $1,550.00
Variance Detected: +$400.00 (25.8% over contracted rate)
Notes: Flag INVOICE_007 using flag_invoice_discrepancy citing unapproved fuel surcharge of $400.00.
""",
    "invoice_008_hannah.txt": """
INVOICE RECORD: INVOICE_008 (INV-2026-008)
==========================================
Invoice ID: INVOICE_008
Reference PO: N/A (Superseded Draft)
Status: SENT — Requested Cancellation by Billing Lead
Issue Date: 2026-11-03
Due Date: 2026-12-03

Bill To:
  Recipient: Hannah Abbott <hannah@novahealth.org>
  Company: NovaHealth Clinical Systems
  Billing Contact: hannah@novahealth.org

Total Amount Due: $4,100.00
Notes: Duplicate draft accidentally dispatched; cancel INVOICE_008 via cancel_invoice and notify hannah@novahealth.org.
""",
    "invoice_009_raj.txt": """
INVOICE RECORD: INVOICE_009 (INV-2026-009)
==========================================
Invoice ID: INVOICE_009
Reference PO: PO-2026-0305
Status: READY TO SEND
Issue Date: 2026-11-10
Due Date: 2026-12-10

Bill To:
  Recipient: Rajesh Patel <raj@alphafintech.io>
  Company: Alpha FinTech Hardware
  Billing Contact: raj@alphafintech.io

Line Items:
  1. Dual-Homed FIX Gateway Appliance (x2) ................ $7,400.00
  2. Solarflare Low-Latency NICs .......................... $1,500.00

Total Amount Due: $8,900.00
Notes: Ready for dispatch to raj@alphafintech.io via send_invoice.
""",
    "Invoice_Discrepancy_Resolution_SOP.md": """
# Invoice Discrepancy Resolution Standard Operating Procedure (SOP-INV-09)

## 1. Automated 3-Way Match Variance Thresholds
Every supplier invoice must match its referenced Purchase Order (`PO-YYYY-NNNN`) and Goods Receipt (`GR-YYYY-NNNN`) across unit price, quantity, and surcharges:
- **Green Auto-Pass**: Variance <= 2.0% AND <= $100.00.
- **Yellow Discrepancy Hold**: Variance > 2.0% OR > $100.00. Must invoke `flag_invoice_discrepancy` before settlement.
- **Red Duplicate / Fraud Hold**: Identical invoice ID or duplicate webhook capture; suspend payout batch immediately.

## 2. Escalation SLAs
- **<= $1,000 variance**: Operator contacts vendor billing lead for revised credit memo within 3 business days.
- **> $1,000 variance**: Escalate to Procurement Manager and freeze pending vendor payout batch.
""",
    # ── 2. Procurement POs, RFQs & Goods Receipts (5 .txt/.md + 3 .pdf/.docx) ─
    "PO-2026-0303_Market_Data_Feed.txt": """
PURCHASE ORDER: PO-2026-0303
============================
PO Number: PO-2026-0303
Vendor: QuantLedger Financial Feeds (Vendor ID: VND-104)
Vendor Email: david.kim@quantledger.ai
Department: Quantitative Research & Capital Markets
Status: APPROVED (Operator Authority < $25,000)

Line Items:
  1. Annual OPRA & Consolidated Tape Market Feed ......... $7,800.00
  2. Co-Location Telemetry Adapter License ................ $2,000.00

Total Amount: $9,800.00
Payment Terms: Net 30
Delivery Schedule: 2026-11-15
""",
    "PO-2026-0304_SOC2_PenTest.txt": """
PURCHASE ORDER: PO-2026-0304
============================
PO Number: PO-2026-0304
Vendor: Vertex Security Group (Vendor ID: VND-106)
Vendor Email: priya@vertexsystems.io
Department: InfoSec & Risk Governance
Status: PENDING_APPROVAL (Requires Finance VP Role — Exceeds $25,000)

Line Items:
  1. Annual SOC2 Type II + PCI-DSS Gap Penetration Test ... $19,400.00
  2. Red-Team API & Prompt-Injection Assessment ........... $9,000.00

Total Amount: $28,400.00
Policy Note: Per Vendor_Onboarding_Policy_v3.pdf, PO-2026-0304 exceeds $25,000 and MUST be approved by a Finance VP or Admin.
""",
    "PO-2026-0306_H100_Memory_Expansion.txt": """
PURCHASE ORDER: PO-2026-0306
============================
PO Number: PO-2026-0306
Vendor: Pacific Semiconductors (Vendor ID: VND-107)
Vendor Email: sophia@pacificsemis.com
Department: ML Platform Engineering
Status: APPROVED

Line Items:
  1. DDR5-5600 ECC RDIMM Kits (64GB x 24) ................. $14,750.00

Total Amount: $14,750.00
Payment Terms: Net 45
""",
    "Goods_Receipt_GR-2026-7741.txt": """
WAREHOUSE GOODS RECEIPT RECORD: GR-2026-7741
============================================
Goods Receipt ID: GR-2026-7741
Purchase Order Ref: PO-2026-0188
Vendor: Acme Corp Enterprise IT (VND-101)
Inspected By: Marcus Chen (Data Center Operations)
Inspection Date: 2026-11-08
Inspection Result: PASSED (100% Serial Match)

Received Items:
  - GPU Inference Node Chassis (Serials ACN-901 to ACN-902): Qty 2 Ordered, Qty 2 Received
  - redundant PSU Kits: Qty 4 Ordered, Qty 4 Received

Recommended Tool Action: Record completion via submit_goods_receipt for PO-2026-0188.
""",
    "RFQ-2026-019_Dark_Fiber_Connectivity.md": """
# Request for Quotation: RFQ-2026-019 — Dedicated Dark Fiber Cross-Connects

- **RFQ ID**: RFQ-2026-019
- **Requesting Team**: Low-Latency Infrastructure & Treasury Connectivity
- **Target Budget Ceiling**: $18,000 / year
- **Bid Deadline**: 2026-11-30
- **Invited Vendors**:
  1. Equinox Carrier Services (`bids@equinoxcarrier.com`) — Est. $16,400/yr
  2. MetroWave Optical (`quotes@metrowave.net`) — Est. $17,200/yr
  3. NorthStar Fiber Networks (`rfp@northstarfiber.io`) — Est. $15,900/yr
- **Tool Mapping**: Use `create_rfq` to solicit refreshed quotes with 99.999% SLA clause.
""",
    # ── 3. Vendor Profiles (5 .txt + 1 .pdf) ─────────────────────────────────
    "Vendor_Profile_VND-101_AcmeCorp.txt": """
VENDOR MASTER PROFILE: VND-101
==============================
Vendor ID: VND-101
Legal Name: Acme Corp Enterprise IT
Primary Contact: Mike Thompson <mike@acmecorp.com>
Category: AI Compute & Rack Hardware
Tax Status: W-9 Verified (EIN ending 4421)
Compliance Standing: PREFERRED TIER-1 (SOC2 + ISO-27001 Valid until 2027-06)
Standard Terms: Net 30 | ACH / PayPal Enterprise Payouts Enabled
YTD Spend: $84,250.00 across 4 POs
""",
    "Vendor_Profile_VND-102_CloudScale.txt": """
VENDOR MASTER PROFILE: VND-102
==============================
Vendor ID: VND-102
Legal Name: CloudScale Infrastructure Inc.
Primary Contact: Emma Watson <emma@cloudscale.io>
Category: Cloud GPU & Object Storage
Tax Status: W-9 Verified
Compliance Standing: APPROVED TIER-1 (SOC2 Type II Valid)
Standard Terms: Net 21
YTD Spend: $112,800.00
""",
    "Vendor_Profile_VND-103_AegisCyber.txt": """
VENDOR MASTER PROFILE: VND-103
==============================
Vendor ID: VND-103
Legal Name: Aegis Cyber Assurance LLC
Primary Contact: Marcus Vance <marcus@aegiscyber.io>
Category: Security Audits & FinTech Compliance
Tax Status: W-9 Verified
Compliance Standing: APPROVED TIER-2 (High-Value Finance VP Sign-Off Required > $25k)
Standard Terms: Net 30
""",
    "Vendor_Profile_VND-104_QuantLedger.txt": """
VENDOR MASTER PROFILE: VND-104
==============================
Vendor ID: VND-104
Legal Name: QuantLedger Financial Feeds Corp
Primary Contact: David Kim <david.kim@quantledger.ai>
Category: Market Data & Tick Feeds
Compliance Standing: APPROVED TIER-1 (FINRA Vendor Checklist Complete)
Standard Terms: Net 30
""",
    "Vendor_Profile_VND-105_MeridianLogistics.txt": """
VENDOR MASTER PROFILE: VND-105
==============================
Vendor ID: VND-105
Legal Name: Meridian Global Freight Ltd.
Primary Contact: Carlos Mendez <carlos@meridianlogistics.com>
Category: Insured IT Freight & White-Glove Delivery
Compliance Standing: WATCHLIST — Recent Surcharge Discrepancy on INVOICE_007
Standard Terms: Net 15
""",
    # ── 4. Payments, Orders, Authorizations, Payouts & Subscriptions (8 docs) ─
    "Payout_Batch_DEC-2026-09.txt": """
SUPPLIER PAYOUT BATCH MANIFEST: PAYOUT-DEC-09
=============================================
Payout Batch ID: PAYOUT-DEC-09
Scheduled Execution: 2026-12-09 14:00 UTC
Funding Currency: USD
Status: STAGED (Requires HITL Confirmation via create_payout_batch)

Beneficiaries:
  1. mike@acmecorp.com (INVOICE_001 ref) ............... $2,450.00
  2. sarah@vendorlabs.io (INVOICE_002 ref) ............. $1,890.00
  3. emma@cloudscale.io (Cloud burst partial) .......... $3,850.00
  4. sophia@pacificsemis.com (Memory kit deposit) ...... $11,230.00

Total Batch Amount: $19,420.00
""",
    "Order_Capture_ORD-88210.txt": """
PAYPAL ORDER AUTHORIZATION RECORD: ORD-88210
==========================================
Order ID: ORD-88210
Merchant / Vendor: Acme Corp Enterprise IT (mike@acmecorp.com)
Authorized Amount: $3,400.00 USD
Authorization Status: APPROVED — Ready to Capture
Valid Until: 2026-11-18
Action: Execute capture_order for ORD-88210 upon warehouse rack check-in.
""",
    "Payment_Authorization_AUTH-55910.txt": """
PAYMENT AUTHORIZATION RECORD: AUTH-55910
========================================
Authorization ID: AUTH-55910
Payer: Treasury Operating Account
Recipient: carlos@meridianlogistics.com
Hold Amount: $2,150.00 USD
Purpose: High-value climate-controlled hardware transit security hold
Expiration: 72 hours from issuance
""",
    "Refund_Request_CAP-77310.txt": """
APPROVED REFUND WORKSHEET: CAP-77310
====================================
Capture ID: CAP-77310
Original Transaction: TXN-8840192
Customer / Counterparty: john@example.com
Original Captured Amount: $2,450.00
Refund Requested: $640.00 (Returned unused 10GbE SFP+ transceiver bundle)
Approval Status: RMA #RMA-4410 Verified — Ready for refund_payment
""",
    "Subscription_SUB-402_DataFeed.txt": """
RECURRING SUBSCRIPTION CONTRACT: SUB-402
========================================
Subscription ID: SUB-402
Plan ID: PLAN-MARKET-TICK-PRO
Provider: QuantLedger Financial Feeds (david.kim@quantledger.ai)
Billing Cycle: Monthly ($1,250.00 / month)
Status: ACTIVE
Next Renewal Date: 2026-12-01
Notes: Query via get_subscription or cancel before 2026-11-28 via cancel_subscription if feed migrates.
""",
    "Subscription_Plan_PLAN-ENT-AI.md": """
# Recurring Billing Plan Spec: PLAN-ENT-AI

- **Plan Name**: ProcureIQ Enterprise Intelligence Seat
- **Plan ID**: PLAN-ENT-AI
- **Monthly Fee**: $2,500.00 / workspace tenant
- **Included Quota**: Unlimited hybrid Tool RAG + Qwen3-4B embeddings + 50,000 Gemini agent turns
- **Setup Fee**: $0.00
- **Lifecycle**: Created via `create_subscription_plan`.
""",
    "Product_Catalog_SKU_Guide_2026.txt": """
PROCUREIQ & FINTECH CATALOG SKUS (2026)
=======================================
SKU-PROC-101 : Enterprise Procurement Copilot Seat ($499.00/mo)
SKU-GPU-204  : Dedicated H100 Inference Reservation ($3,200.00/block)
SKU-DATA-309 : Institutional Market Tick Connector ($1,250.00/mo)
SKU-SEC-412  : Automated SOC2 / FINRA Audit Archiver ($1,700.00/yr)
Use `list_products` or `create_product` to maintain PayPal Checkout catalog SKUs.
""",
    "Treasury_FX_and_Liquidity_Buffer_Policy.md": """
# Corporate Treasury FX & Liquidity Buffer Policy (TREAS-2026-02)

1. **Minimum USD Operating Balance**: Maintain >= $150,000.00 in primary PayPal Enterprise Treasury wallet before triggering automated `create_payout_batch`.
2. **Multi-Currency Exposure**: EUR and GBP vendor invoices exceeding $10,000 equivalent require checking live account balances via `get_balance` prior to FX conversion.
3. **Emergency Reserve Alert**: Any payout drawing balance below $50,000 triggers mandatory `finance_vp` sign-off.
""",
    # ── 5. Disputes, KYC & Fraud Risk (5 .txt/.md + 1 .pdf) ──────────────────
    "Dispute_PP-D-20418_Duplicate_Billing.txt": """
DISPUTE CASE FILE: PP-D-20418
=============================
Dispute ID: PP-D-20418
Counterparty: Meridian Global Freight (carlos@meridianlogistics.com)
Transaction ID: TXN-9910421
Disputed Amount: $1,950.00 USD
Reason Code: DUPLICATE_TRANSACTION
Status: OPEN — Seller Evidence Matches Buyer Duplicate Claim
Notes: Accept refund via accept_dispute_claim for PP-D-20418 OR reconcile against INVOICE_007 discrepancy.
""",
    "Dispute_PP-D-30912_SLA_Penalty.txt": """
DISPUTE CASE FILE: PP-D-30912
=============================
Dispute ID: PP-D-30912
Counterparty: CloudScale Infrastructure Inc. (emma@cloudscale.io)
Transaction ID: TXN-9941208
Disputed Amount: $4,200.00 USD
Reason Code: SERVICE_SLA_CREDIT_DISPUTE
Status: UNDER_REVIEW — Counter-Evidence Deadline 2026-11-22
Summary: Client claims p99 API latency exceeded 400ms during Q3 rollout; internal telemetry shows 99.97% SLA uptime (187ms p99).
Action: Upload uptime log evidence bundle SLA-LOG-Q3 via provide_dispute_evidence or escalate via escalate_dispute.
""",
    "Dispute_PP-D-41005_Messages_Log.md": """
# Dispute Communication Thread: PP-D-30912 / PP-D-41005

- **2026-11-02 (Vendor - Emma Watson)**: Attached Q3 Prometheus latency percentiles (`p95=112ms`, `p99=187ms`).
- **2026-11-04 (Buyer Finance)**: Requested raw availability logs excluding scheduled Sunday 02:00 UTC maintenance window.
- **2026-11-06 (ProcureIQ Legal)**: Prepared rebuttal dossier; inspect live updates via `get_dispute_messages`.
""",
    "KYC_Verification_Case_USR-409.txt": """
COUNTERPARTY KYC / BENEFICIAL OWNERSHIP CHECK: USR-409
====================================================
User / Entity ID: USR-409 (Pacific Semiconductors Authorized Signatory: Sophia Chen)
Verification Tier: CIP + Enhanced Due Diligence (EDD)
Status: VERIFIED_PASS
Sanctions Screening (OFAC / EU / UK HMT): CLEAR (0 Matches)
UBO Ownership Check: Verified >25% Ultimate Beneficial Owners documented
Next Review Date: 2027-11-01
Tool Reference: get_identity_verification
""",
    "Fraud_Risk_Assessment_TXN-88412.txt": """
REAL-TIME FRAUD & RISK TELEMETRY: TXN-88412
==========================================
Transaction ID: TXN-88412
Requested Payout Recipient: unknown-relay@offshore-shell.example
Amount: $14,900.00
Composite Risk Score: 0.84 / 1.00 (HIGH RISK)
Signals Triggered:
  - Newly registered domain (< 7 days old)
  - First-time payout anomaly exceeding 3x vendor baseline
  - ASN geo-mismatch vs W-9 domicile
Recommendation: BLOCK transaction via get_risk_assessment review and trigger KYC re-verification.
""",
    # ── 6. Analytics, Budgets, Webhooks & FinTech Compliance (4 .md/.txt + 2 .pdf) ─
    "PayPal_Settlement_Reconciliation_Nov2026.txt": """
MONTHLY SETTLEMENT & FEE RECONCILIATION: STL-NOV-2026
=====================================================
Settlement Batch: STL-NOV-2026
Reporting Period: 2026-11-01 to 2026-11-30
Gross Settled Volume: $148,920.00 USD
PayPal Merchant Processing Fees: $3,112.40 USD (2.09% blended)
Dispute Chargeback Adjustments: -$640.00 USD
Net Treasury Deposit: $145,167.60 USD
Reconciliation Variance: $0.00 (BALANCED)
Tool Reference: get_settlement_report / export_transactions_csv
""",
    "Revenue_Breakdown_EMEA_NA_2026.md": """
# Q4 2026 Regional Revenue & Fee Breakdown

- **North America (NA)**: $98,420.00 gross (66.1%), Net Margin 78.4%, Primary driver: Enterprise SaaS & Data Feeds.
- **EMEA (UK / EU)**: $36,800.00 gross (24.7%), Net Margin 72.1%, EUR/GBP FX hedge active.
- **APAC**: $13,700.00 gross (9.2%), Net Margin 69.5%.
- **Combined Q4 Run-Rate**: Query `get_revenue_breakdown` and `get_sales_report` for live rollup slices.
""",
    "Webhook_HMAC_Verification_Runbook.md": """
# Webhook Event & HMAC-SHA256 Verification Runbook

- **Sample Verified Event**: `WH-EVT-9012` (`PAYMENT.CAPTURE.COMPLETED`, 2026-11-10T09:14:22Z)
- **Dead-Letter Queue Policy**: Failed webhook deliveries retry exponentially (1m, 5m, 15m, 1h); duplicate event IDs are idempotently ignored so duplicate charges like `TXN-9982410` do not re-trigger.
- **Verification**: Always inspect `list_webhook_events` and run `verify_webhook_signature` passing transmission ID, timestamp, cert URL, and CRC32 before replaying settlement webhooks.
""",
    "Capital_Markets_Vendor_Governance_SOP.md": """
# Capital Markets & FinTech Vendor Governance SOP (CM-GOV-2026)

## Scope
Applies to market data vendors (`QuantLedger`), trading/FIX connectivity providers (`Alpha FinTech`), and AI infrastructure partners supplying enterprise financial operations.

## Governance Controls
1. **Segregation of Duties (SoD)**: The operator submitting a purchase order or vendor creation (`create_vendor`) cannot self-approve POs above $25,000; `finance_vp` or `admin` cryptographic/RBAC approval is strictly required.
2. **Immutable Audit Trail**: Every tool selection, KB enrichment source, parameter payload, HITL approval, and RBAC denial is persisted append-only in PostgreSQL `audit_log` with `tenant_id` scoping (aligned with SEC 17a-4 auditability principles).
3. **Quarterly Spend Concentration Review**: Run `get_spend_by_vendor` and `get_budget_utilization` monthly to ensure single-vendor concentration stays below 35% of departmental IT spend.
""",
}

PDF_DOCS = [
    (
        "invoice_010_sophia.pdf",
        "INVOICE RECORD: INVOICE_010 (INV-2026-010)",
        """
Invoice ID: INVOICE_010
Reference PO: PO-2026-0306
Status: APPROVED FOR PAYMENT (Net 45)
Issue Date: 2026-11-07
Due Date: 2026-12-22

Bill To:
  Recipient: Sophia Chen <sophia@pacificsemis.com>
  Company: Pacific Semiconductors
  Billing Contact: sophia@pacificsemis.com

Line Items:
  1. DDR5-5600 ECC RDIMM Kits (64GB x 24 Units) ........... $14,750.00

Subtotal: $14,750.00
Tax: $0.00 (Capital Equipment Exemption)
Total Amount Due: $14,750.00
Notes: Match against PO-2026-0306 before issuing PayPal Enterprise disbursement.
""",
    ),
    (
        "PO-2026-0305_FIX_Gateway_Servers.pdf",
        "PURCHASE ORDER: PO-2026-0305 — HIGH-VALUE HARDWARE",
        """
PO Number: PO-2026-0305
Vendor: Alpha FinTech Hardware (Vendor ID: VND-108)
Vendor Email: raj@alphafintech.io
Department: Capital Markets Connectivity Engineering
Approval Tier Required: Finance VP (Amount exceeds $25,000 threshold)

Line Items:
  1. Ultra-Low-Latency Dual-Homed FIX Gateway Appliance (x4) .. $35,200.00
  2. Hardware Timestamping FPGA Expansion Cards ............... $9,000.00

Total Amount: $44,200.00
Payment Terms: Net 30
Policy Citation: Requires role finance_vp or admin under Vendor_Onboarding_Policy_v3.pdf.
""",
    ),
    (
        "Approved_Vendor_Tier_Matrix_2026.pdf",
        "PROCUREIQ APPROVED VENDOR & APPROVAL AUTHORITY MATRIX (2026)",
        """
Document ID: POL-MATRIX-2026
Effective Date: 2026-01-01

Approval Thresholds:
  Tier 1 (viewer)     : Read-only KB RAG, analytics reports, vendor & invoice lookup. No write actions.
  Tier 2 (operator)   : Create invoices, send reminders, approve Purchase Orders UP TO $25,000.00.
  Tier 3 (finance_vp) : Mandatory approval authority for ALL Purchase Orders ABOVE $25,000.00,
                        tool registry deletions, and circuit-breaker resets.
  Tier 4 (admin)      : Full platform administration across tenants and security controls.

Enforcement Rule:
  Attempting approve_purchase_order above $25,000.00 as role 'operator' is blocked with HTTP 403
  and recorded as action 'rbac_denied' in audit_log.
""",
    ),
    (
        "Chargeback_and_Arbitration_Evidence_Rules.pdf",
        "CHARGEBACK & DISPUTE ARBITRATION EVIDENCE GUIDELINES",
        """
Document ID: FIN-ARB-2026

Mandatory Evidence Artifacts by Reason Code:
  1. ITEM_NOT_RECEIVED      : Carrier Proof of Delivery (POD) + signed Carrier Manifest ID.
  2. DUPLICATE_TRANSACTION  : Settlement ledger export verifying single capture vs duplicate webhook retry.
  3. SERVICE_SLA_DISPUTE    : Exported p95/p99 latency & uptime logs (e.g., SLA-LOG-Q3 for PP-D-30912).
  4. UNAUTHORIZED_PAYMENT   : IP/ASN risk telemetry + KYC CIP check (get_risk_assessment).

SLA Window: Respond within 7 calendar days of dispute opening using provide_dispute_evidence.
""",
    ),
    (
        "IT_Department_Budget_FY2026.pdf",
        "FY2026 IT & AI INFRASTRUCTURE BUDGET UTILIZATION BRIEF",
        """
Budget Code: DEPT-IT-AI-2026
Fiscal Year: FY2026 (Q1-Q4)
Total Annual Approved Allocation: $1,200,000.00
YTD Committed & Disbursed Spend: $976,800.00 (81.4% Utilization)
Remaining Available Headroom: $223,200.00

Breakdown by Category:
  - GPU Clusters & Cloud Compute (CloudScale, Acme) : $612,000.00 (84.0% utilized)
  - Cybersecurity & SOC2 Audits (Aegis, Vertex)     : $148,000.00 (79.5% utilized)
  - Market Data & Low-Latency Networking            : $132,800.00 (76.2% utilized)
  - SaaS Copilot & Developer Tooling                : $84,000.00  (74.1% utilized)

Alert Policy: Utilization exceeding 85% freezes non-essential Tier-2 purchases without Finance VP sign-off.
Tool Mapping: Query via get_budget_utilization or rag_query.
""",
    ),
    (
        "SOC2_FinTech_Audit_Compliance_Guide.pdf",
        "PROCUREIQ SOC2 TYPE II & FINTECH SECURITY ARCHITECTURE GUIDE",
        """
Document ID: SEC-SOC2-2026
Last Audited: 2026-11-01

Key Security Controls Implemented in ProcureIQ Platform:
  1. Durable PostgreSQL Checkpointing: LangGraph states and HITL interrupts persist in
     agent_checkpoints / agent_checkpoint_blobs / agent_checkpoint_writes across server restarts.
  2. Multi-Tenant Isolation: kb_chunks, sessions, and audit_log strictly partition by tenant_id
     so queries and KB RAG never leak documents across customer workspaces.
  3. Role-Based Access Control (RBAC): HS256 JWT tokens and X-API-Key identities enforce
     viewer, operator, finance_vp ($25,000+ PO gate), and admin privileges.
  4. Transport Security & Rate Limiting: TLS certificate verification enabled by default
     (GEMINI_VERIFY_SSL=true) and sliding-window IP rate limiting (HTTP 429).
""",
    ),
]

DOCX_DOCS = [
    (
        "PO-2026-0301_Security_Audit.docx",
        "PURCHASE ORDER: PO-2026-0301 — ENTERPRISE CYBER ASSURANCE",
        """
PO Number: PO-2026-0301
Vendor: Aegis Cyber Assurance LLC (Vendor ID: VND-103)
Vendor Email: marcus@aegiscyber.io
Department: Enterprise Information Security
Approval Status: PENDING_APPROVAL

Scope of Work:
  1. Comprehensive SOC2 Type II Attestation & Control Audit ($18,500.00)
  2. FinTech Payment Gateway & Smart-Router Penetration Assessment ($13,500.00)

Total Amount: $32,000.00
Payment Terms: Net 30

Governance Gate: Because Total Amount ($32,000.00) exceeds the $25,000.00 procurement limit, approval via approve_purchase_order MUST be executed by a user holding role 'finance_vp' or 'admin' per Vendor_Onboarding_Policy_v3.pdf.
""",
    ),
    (
        "PO-2026-0302_Cloud_GPUs.docx",
        "PURCHASE ORDER: PO-2026-0302 — CLOUD GPU RESERVATION",
        """
PO Number: PO-2026-0302
Vendor: CloudScale Infrastructure Inc. (Vendor ID: VND-102)
Vendor Email: emma@cloudscale.io
Department: AI Engineering
Approval Status: PENDING_OPERATOR_APPROVAL

Line Items:
  1. Reserved Multi-Node GPU Pool Q4 Allocation ($14,650.00)
  2. Dedicated NVMe Checkpoint Storage ($3,850.00)

Total Amount: $18,500.00
Payment Terms: Net 21

Governance Gate: Total Amount ($18,500.00) is below the $25,000.00 Finance VP threshold and may be approved by an 'operator' role user.
""",
    ),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in TEXT_DOCS.items():
        write_txt_or_md(name, body)
    for name, title, body in PDF_DOCS:
        write_pdf(name, title, body)
    for name, title, body in DOCX_DOCS:
        write_docx(name, title, body)

    all_files = sorted(p.name for p in OUT_DIR.iterdir() if p.is_file())
    print(f"Generated {len(TEXT_DOCS) + len(PDF_DOCS) + len(DOCX_DOCS)} new enterprise docs.")
    print(f"Total files now in sample_docs/: {len(all_files)}")


if __name__ == "__main__":
    main()

