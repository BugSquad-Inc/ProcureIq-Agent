# Invoice Discrepancy Resolution Standard Operating Procedure (SOP-INV-09)

## 1. Automated 3-Way Match Variance Thresholds
Every supplier invoice must match its referenced Purchase Order (`PO-YYYY-NNNN`) and Goods Receipt (`GR-YYYY-NNNN`) across unit price, quantity, and surcharges:
- **Green Auto-Pass**: Variance <= 2.0% AND <= $100.00.
- **Yellow Discrepancy Hold**: Variance > 2.0% OR > $100.00. Must invoke `flag_invoice_discrepancy` before settlement.
- **Red Duplicate / Fraud Hold**: Identical invoice ID or duplicate webhook capture; suspend payout batch immediately.

## 2. Escalation SLAs
- **<= $1,000 variance**: Operator contacts vendor billing lead for revised credit memo within 3 business days.
- **> $1,000 variance**: Escalate to Procurement Manager and freeze pending vendor payout batch.
