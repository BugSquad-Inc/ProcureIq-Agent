# Corporate Treasury FX & Liquidity Buffer Policy (TREAS-2026-02)

1. **Minimum USD Operating Balance**: Maintain >= $150,000.00 in primary PayPal Enterprise Treasury wallet before triggering automated `create_payout_batch`.
2. **Multi-Currency Exposure**: EUR and GBP vendor invoices exceeding $10,000 equivalent require checking live account balances via `get_balance` prior to FX conversion.
3. **Emergency Reserve Alert**: Any payout drawing balance below $50,000 triggers mandatory `finance_vp` sign-off.
