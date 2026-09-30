from __future__ import annotations

import copy
import pathlib
import runpy
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = runpy.run_path(str(ROOT / "tools/check-renderer-audit.py"))


class RendererAuditTest(unittest.TestCase):
    def setUp(self):
        self.lock = (ROOT / "docker/package-lock.json").read_bytes()
        self.report = {
            "auditReportVersion": 2,
            "vulnerabilities": {"dompurify": {
                "name": "dompurify", "severity": "low", "nodes": ["node_modules/dompurify"],
                "via": [{"name": "dompurify", "severity": "low", "url": "https://github.com/advisories/" + AUDIT["ADVISORY"], "title": AUDIT["TITLE"]}],
            }},
            "metadata": {"vulnerabilities": {"info": 0, "low": 1, "moderate": 0, "high": 0, "critical": 0, "total": 1}},
        }

    def check(self, report, lock=None, image=None, code=1):
        return AUDIT["check"](report, lock if lock is not None else self.lock, image or AUDIT["IMAGE_ID"], code)

    def test_exact_approved_advisory_and_clean_report(self):
        self.assertEqual(self.check(self.report)["accepted_advisories"], [AUDIT["ADVISORY"]])
        clean = {"auditReportVersion": 2, "vulnerabilities": {},
                 "metadata": {"vulnerabilities": dict.fromkeys(self.report["metadata"]["vulnerabilities"], 0)}}
        self.assertEqual(self.check(clean, code=0)["accepted_advisories"], [])

    def test_any_other_finding_or_changed_advisory_is_blocking(self):
        for kind in ("package", "severity", "advisory", "title", "extra", "nodes", "totals", "error", "missing"):
            with self.subTest(kind=kind):
                report = copy.deepcopy(self.report)
                item = report["vulnerabilities"]["dompurify"]
                if kind == "package":
                    report["vulnerabilities"]["other"] = item
                elif kind == "severity":
                    item["severity"] = "moderate"
                elif kind == "advisory":
                    item["via"][0]["url"] = "https://github.com/advisories/GHSA-other"
                elif kind == "title":
                    item["via"][0]["title"] = "Different preconditions"
                elif kind == "extra":
                    item["via"].append(item["via"][0])
                elif kind == "nodes":
                    item["nodes"].append("node_modules/other/node_modules/dompurify")
                elif kind == "totals":
                    report["metadata"]["vulnerabilities"]["high"] = 1
                elif kind == "error":
                    report["error"] = {"code": "registry-unavailable"}
                else:
                    del report["auditReportVersion"]
                with self.assertRaises(ValueError):
                    self.check(report)

    def test_exception_cannot_transfer_to_other_bytes_images_or_failed_audits(self):
        with self.assertRaises(ValueError):
            self.check(self.report, lock=self.lock + b"\n")
        with self.assertRaises(ValueError):
            self.check(self.report, image="sha256:" + "a" * 64)
        for code in (0, 2, 127):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.check(self.report, code=code)
