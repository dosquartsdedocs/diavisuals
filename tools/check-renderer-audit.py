#!/usr/bin/env python3
"""Gate npm audit with one owner-approved exception for the exact reused image."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

IMAGE_ID = "sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846"
LOCK_SHA256 = "48e4128ecfebd45fd751aef50d96b10b01e9768ee0797a441735c4eb5de2b438"
ADVISORY = "GHSA-p98j-92pf-mc4p"
TITLE = "DOMPurify: IN_PLACE: node-removing afterSanitize hook leaves detached subtree event handlers armed, causing DOM XSS"


def check(report: dict, lock_bytes: bytes, image_id: str, audit_exit_code: int) -> dict:
    if image_id != IMAGE_ID or hashlib.sha256(lock_bytes).hexdigest() != LOCK_SHA256:
        raise ValueError("audit exception does not cover this renderer image or lock")
    lock = json.loads(lock_bytes)
    if lock["packages"]["node_modules/dompurify"]["version"] != "3.4.14":
        raise ValueError("audit exception does not cover this DOMPurify version")
    if not isinstance(report, dict) or report.get("auditReportVersion") != 2 or "error" in report:
        raise ValueError("npm audit did not return a complete v2 report")
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict) or set(vulnerabilities) - {"dompurify"}:
        raise ValueError("unexpected npm vulnerabilities; owner review required")
    counts = {"info": 0, "low": len(vulnerabilities), "moderate": 0, "high": 0, "critical": 0, "total": len(vulnerabilities)}
    if report.get("metadata", {}).get("vulnerabilities") != counts or audit_exit_code != (1 if vulnerabilities else 0):
        raise ValueError("inconsistent npm audit severity totals or exit code")
    if vulnerabilities:
        item = vulnerabilities["dompurify"]
        if not isinstance(item, dict) or item.get("name") != "dompurify" or item.get("severity") != "low" or item.get("nodes") != ["node_modules/dompurify"]:
            raise ValueError("unexpected DOMPurify finding scope")
        via = item.get("via")
        if not isinstance(via, list) or len(via) != 1 or not isinstance(via[0], dict):
            raise ValueError("unexpected DOMPurify advisory inventory")
        expected = {"name": "dompurify", "severity": "low", "url": f"https://github.com/advisories/{ADVISORY}", "title": TITLE}
        if any(via[0].get(key) != value for key, value in expected.items()):
            raise ValueError("unapproved advisory or changed severity/title")
    return {"ok": True, "accepted_advisories": [ADVISORY] if vulnerabilities else [], "image_id": image_id,
            "lock_sha256": LOCK_SHA256, "decision": "docs/renderer-audit-exception-2026-09-30.md"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--lock", type=Path, default=Path("docker/package-lock.json"))
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--audit-exit-code", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    try:
        if args.report.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("npm audit report exceeds the supported bound")
        result = check(json.loads(args.report.read_bytes()), args.lock.read_bytes(), args.image_id, args.audit_exit_code)
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
