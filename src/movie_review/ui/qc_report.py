"""QC Report UI (T095, optional Phase 11).

Visual report for quality control results. Shows the overall verdict,
per-metric scores against thresholds, the quality gate, and render
validation. Reads the ``qc/quality-report.json`` artifact produced by
the quality report stage (T069).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from movie_review.artifacts import manager as artifacts
from movie_review.ui.safe_json import json_for_script


class QualityReportUI:
    """Visual UI for the QC report."""

    def __init__(self, jobs_dir: str | Path, job_id: str):
        self.jobs_dir = Path(jobs_dir)
        self.job_id = job_id

    def load(self) -> dict[str, Any]:
        """Load QC report from job artifacts."""
        report_path = self.jobs_dir / self.job_id / "qc" / "quality-report.json"

        if not report_path.is_file():
            return self._empty_report()

        document = artifacts.read_json(report_path)
        return self._build_from_report(document)

    def _build_from_report(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build UI data from the quality report document."""
        raw_metrics = document.get("metrics", []) or []
        metrics = []
        for metric in raw_metrics:
            score = float(metric.get("score", 0.0))
            threshold = float(metric.get("threshold", 0.0))
            metrics.append(
                {
                    "name": metric.get("name", ""),
                    "score": score,
                    "threshold": threshold,
                    "detail": metric.get("detail", ""),
                    "passed": score >= threshold,
                }
            )

        gate = document.get("gate") or {}
        validation = document.get("validation") or {}
        overall = float(document.get("overall", 0.0))

        return {
            "job_id": self.job_id,
            "passed": bool(document.get("passed", False)),
            "overall": overall,
            "metrics": metrics,
            "metric_count": len(metrics),
            "passed_count": sum(1 for m in metrics if m["passed"]),
            "failed_count": sum(1 for m in metrics if not m["passed"]),
            "gate": {
                "passed": bool(gate.get("passed", False)),
                "failures": list(gate.get("failures", [])),
            },
            "validation": {
                "ok": bool(validation.get("ok", False)),
                "failures": list(validation.get("failures", [])),
            },
        }

    def _empty_report(self) -> dict[str, Any]:
        """Return an empty report structure."""
        return {
            "job_id": self.job_id,
            "passed": False,
            "overall": 0.0,
            "metrics": [],
            "metric_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "gate": {"passed": False, "failures": []},
            "validation": {"ok": False, "failures": []},
        }

    def to_json(self) -> str:
        """Export report as JSON."""
        return json.dumps(self.load(), indent=2)

    def to_html(self) -> str:
        """Generate standalone HTML QC report."""
        data = self.load()
        return self._html_template(data)

    def _html_template(self, data: dict[str, Any]) -> str:
        """Generate HTML with the QC report summary."""
        json_data = json_for_script(data)
        metrics_html = self._render_metrics_html(data["metrics"])
        verdict_class = "pass" if data["passed"] else "fail"
        verdict_text = "PASSED" if data["passed"] else "FAILED"
        gate_class = "pass" if data["gate"]["passed"] else "fail"
        validation_class = "pass" if data["validation"]["ok"] else "fail"
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"    <title>QC Report - Job {data['job_id']}</title>\n"
            "    <style>\n"
            "        * { box-sizing: border-box; margin: 0; padding: 0; }\n"
            "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }\n"
            "        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }\n"
            "        header { margin-bottom: 20px; }\n"
            "        h1 { color: #333; }\n"
            "        .meta { color: #666; margin-top: 6px; }\n"
            "        .verdict { padding: 16px 24px; border-radius: 8px; font-size: 20px; font-weight: 700; margin-bottom: 20px; }\n"
            "        .verdict.pass { background: #d4edda; color: #155724; }\n"
            "        .verdict.fail { background: #f8d7da; color: #721c24; }\n"
            "        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 20px; }\n"
            "        .card { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }\n"
            "        .card .label { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.05em; }\n"
            "        .card .value { font-size: 28px; font-weight: 700; color: #333; margin-top: 4px; }\n"
            "        .section { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; overflow: hidden; }\n"
            "        .section-header { padding: 14px 16px; background: #f8f9fa; font-weight: 600; color: #333; border-bottom: 1px solid #eee; }\n"
            "        table { width: 100%; border-collapse: collapse; }\n"
            "        th, td { padding: 10px 16px; text-align: left; border-bottom: 1px solid #eee; font-size: 14px; }\n"
            "        th { background: #fafafa; color: #555; font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }\n"
            "        .score-bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; min-width: 120px; }\n"
            "        .score-bar .fill { height: 100%; border-radius: 4px; }\n"
            "        .fill.pass { background: #28a745; }\n"
            "        .fill.fail { background: #dc3545; }\n"
            "        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }\n"
            "        .badge.pass { background: #d4edda; color: #155724; }\n"
            "        .badge.fail { background: #f8d7da; color: #721c24; }\n"
            "        .failures { color: #721c24; font-size: 13px; }\n"
            "        .empty-state { text-align: center; padding: 48px; color: #999; }\n"
            "        pre { background: #f8f9fa; padding: 12px; border-radius: 4px; overflow: auto; font-size: 12px; }\n"
            "        @media (max-width: 768px) { th, td { padding: 8px 10px; } }\n"
            "    </style>\n"
            "</head>\n"
            "<body>\n"
            '    <div class="container">\n'
            "        <header>\n"
            "            <h1>QC Report</h1>\n"
            f'            <div class="meta">Job: {data["job_id"]}</div>\n'
            "        </header>\n"
            f'        <div class="verdict {verdict_class}">{verdict_text}</div>\n'
            '        <div class="summary">\n'
            f'            <div class="card"><div class="label">Overall</div><div class="value">{data["overall"]:.1f}</div></div>\n'
            f'            <div class="card"><div class="label">Metrics</div><div class="value">{data["metric_count"]}</div></div>\n'
            f'            <div class="card"><div class="label">Passed</div><div class="value">{data["passed_count"]}</div></div>\n'
            f'            <div class="card"><div class="label">Failed</div><div class="value">{data["failed_count"]}</div></div>\n'
            "        </div>\n"
            '        <div class="section">\n'
            '            <div class="section-header">Quality Metrics</div>\n'
            f"            {metrics_html}\n"
            "        </div>\n"
            '        <div class="section">\n'
            '            <div class="section-header">Quality Gate</div>\n'
            "            <table>\n"
            "                <tr><th>Status</th><th>Failures</th></tr>\n"
            f'                <tr><td><span class="badge {gate_class}">{"PASSED" if data["gate"]["passed"] else "FAILED"}</span></td><td class="failures">{self._render_list(data["gate"]["failures"])}</td></tr>\n'
            "            </table>\n"
            "        </div>\n"
            '        <div class="section">\n'
            '            <div class="section-header">Render Validation</div>\n'
            "            <table>\n"
            "                <tr><th>Status</th><th>Failures</th></tr>\n"
            f'                <tr><td><span class="badge {validation_class}">{"OK" if data["validation"]["ok"] else "FAILED"}</span></td><td class="failures">{self._render_list(data["validation"]["failures"])}</td></tr>\n'
            "            </table>\n"
            "        </div>\n"
            "    </div>\n"
            "    <script>\n"
            f"        const data = {json_data};\n"
            "    </script>\n"
            "</body>\n"
            "</html>"
        )

    def _render_metrics_html(self, metrics: list[dict[str, Any]]) -> str:
        """Render the metrics table rows (Python side)."""
        if not metrics:
            return '<div class="empty-state">No metrics recorded</div>'

        def escape_html(text: str) -> str:
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )

        rows = []
        for metric in metrics:
            score = metric["score"]
            threshold = metric["threshold"]
            passed = metric["passed"]
            bar_class = "pass" if passed else "fail"
            badge_class = "pass" if passed else "fail"
            pct = max(0.0, min(100.0, score))
            rows.append(
                "<tr>"
                "<td>" + escape_html(metric["name"]) + "</td>"
                "<td>"
                '<div class="score-bar"><div class="fill '
                + bar_class
                + '" style="width: '
                + str(pct)
                + '%"></div></div>'
                "</td>"
                "<td>" + str(score) + "</td>"
                "<td>" + str(threshold) + "</td>"
                '<td><span class="badge '
                + badge_class
                + '">'
                + ("PASS" if passed else "FAIL")
                + "</span></td>"
                "<td>" + escape_html(metric.get("detail", "")) + "</td>"
                "</tr>"
            )

        return (
            "<table>"
            "<tr><th>Metric</th><th>Score</th><th>Value</th><th>Threshold</th><th>Status</th><th>Detail</th></tr>"
            + "".join(rows)
            + "</table>"
        )

    @staticmethod
    def _render_list(items: list[str]) -> str:
        """Render a list of failure strings, or a dash when empty."""
        if not items:
            return "&mdash;"
        return "<br>".join(str(item) for item in items)
