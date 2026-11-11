"""
upload_sample_docs.py — Upload all enterprise documents in `sample_docs/` to the
ProcureIQ Knowledge Base API (`POST /api/kb/upload`) under a chosen tenant.

Usage:
  python scripts/upload_sample_docs.py
  python scripts/upload_sample_docs.py --url http://127.0.0.1:8000 --tenant default --role finance_vp
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_docs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload sample_docs/ into ProcureIQ KB")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--tenant", default="default", help="Target X-Tenant-ID workspace")
    parser.add_argument("--role", default="finance_vp", help="X-User-Role header")
    args = parser.parse_args()

    files = sorted(p for p in SAMPLE_DIR.iterdir() if p.is_file())
    if not files:
        print(f"No files found in {SAMPLE_DIR}")
        return 1

    base_url = args.url.rstrip("/")
    headers = {"X-Tenant-ID": args.tenant, "X-User-Role": args.role}
    print(f"Uploading {len(files)} documents from {SAMPLE_DIR} -> {base_url} (tenant={args.tenant})...")

    uploaded = 0
    total_chunks = 0
    started = time.perf_counter()

    with httpx.Client(timeout=120.0, headers=headers) as client:
        for idx, path in enumerate(files, start=1):
            with path.open("rb") as f:
                resp = client.post(
                    f"{base_url}/api/kb/upload",
                    files={"file": (path.name, f, "application/octet-stream")},
                )
            if resp.status_code not in (200, 201):
                print(f"[{idx}/{len(files)}] FAILED {path.name}: {resp.status_code} {resp.text}")
                return 1
            data = resp.json()
            chunks = int(data.get("chunks_created", 0))
            uploaded += 1
            total_chunks += chunks
            if idx % 10 == 0 or idx == len(files):
                print(f"  Progress: {idx}/{len(files)} uploaded (total chunks indexed={total_chunks})")

        summary = client.get(f"{base_url}/api/kb/documents").json()

    elapsed = round(time.perf_counter() - started, 2)
    print(
        f"Done in {elapsed}s -> uploaded={uploaded}, total_chunks={total_chunks}, "
        f"kb_documents_in_tenant={summary.get('total_documents')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

