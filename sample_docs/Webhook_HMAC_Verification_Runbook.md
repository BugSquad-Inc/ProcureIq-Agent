# Webhook Event & HMAC-SHA256 Verification Runbook

- **Sample Verified Event**: `WH-EVT-9012` (`PAYMENT.CAPTURE.COMPLETED`, 2026-11-10T09:14:22Z)
- **Dead-Letter Queue Policy**: Failed webhook deliveries retry exponentially (1m, 5m, 15m, 1h); duplicate event IDs are idempotently ignored so duplicate charges like `TXN-9982410` do not re-trigger.
- **Verification**: Always inspect `list_webhook_events` and run `verify_webhook_signature` passing transmission ID, timestamp, cert URL, and CRC32 before replaying settlement webhooks.
