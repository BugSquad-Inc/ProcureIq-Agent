# Capital Markets & FinTech Vendor Governance SOP (CM-GOV-2026)

## Scope
Applies to market data vendors (`QuantLedger`), trading/FIX connectivity providers (`Alpha FinTech`), and AI infrastructure partners supplying enterprise financial operations.

## Governance Controls
1. **Segregation of Duties (SoD)**: The operator submitting a purchase order or vendor creation (`create_vendor`) cannot self-approve POs above $25,000; `finance_vp` or `admin` cryptographic/RBAC approval is strictly required.
2. **Immutable Audit Trail**: Every tool selection, KB enrichment source, parameter payload, HITL approval, and RBAC denial is persisted append-only in PostgreSQL `audit_log` with `tenant_id` scoping (aligned with SEC 17a-4 auditability principles).
3. **Quarterly Spend Concentration Review**: Run `get_spend_by_vendor` and `get_budget_utilization` monthly to ensure single-vendor concentration stays below 35% of departmental IT spend.
