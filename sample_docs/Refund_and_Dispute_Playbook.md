# Enterprise Refund, Capture & Dispute Resolution Playbook

## 1. Payment Capture Refunds
- Refunds against captured payments (e.g., Capture ID `CAP-7741` linked to `TXN-88412`) are permitted within **180 days** of settlement.
- Partial refunds up to **$500.00** require standard HITL confirmation in UI; full refunds exceeding **$500.00** require Finance Controller sign-off.

## 2. Counterparty Dispute Handling
- Open dispute `PP-D-12345` (`$1,280.00` — buyer `user_123`) has supporting shipment proof in Carrier Manifest `#GF-88210`.
- When submitting evidence via `provide_dispute_evidence`, attach `evidence_type: CARRIER_MANIFEST` and manifest `#GF-88210`.
- Counterparty claims unresolved beyond **7 business days** must be escalated via `escalate_dispute`.

