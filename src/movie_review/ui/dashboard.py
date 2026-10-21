"""Job Dashboard (T089, optional Phase 11).

Simple web-based dashboard for monitoring job progress. Serves static HTML
with JavaScript that polls the CLI's job database for status updates.
"""

from __future__ import annotations

import http.server
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from movie_review.config.settings import load_settings
from movie_review.storage.database import bootstrap


class JobDashboard:
    """Web dashboard for job monitoring."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, db_path: str | None = None):
        self.host = host
        self.port = port
        self.db_path = db_path
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _get_db_path(self) -> Path:
        if self.db_path:
            return Path(self.db_path)
        settings = load_settings()
        return Path(settings.paths.data_dir) / "jobs.db"

    def get_jobs(self) -> list[dict[str, Any]]:
        """Fetch all jobs from the database."""
        conn = sqlite3.connect(str(bootstrap(self._get_db_path())))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT job_id, input_file, status, failed_stage, error,
                       retry_count, created_at, updated_at
                FROM jobs ORDER BY created_at DESC
            """).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_job_details(self, job_id: str) -> dict[str, Any] | None:
        """Fetch detailed info for a single job including artifacts."""
        conn = sqlite3.connect(str(bootstrap(self._get_db_path())))
        conn.row_factory = sqlite3.Row
        try:
            job_row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not job_row:
                return None

            job = dict(job_row)

            # Get artifacts
            artifact_rows = conn.execute(
                """
                SELECT artifact_id, stage, version, created_at, input_hash,
                       output_hash, model, prompt_version
                FROM artifacts WHERE job_id = ? ORDER BY version
            """,
                (job_id,),
            ).fetchall()
            job["artifacts"] = [dict(row) for row in artifact_rows]

            return job
        finally:
            conn.close()

    def start(self, open_browser: bool = False) -> None:
        """Start the dashboard HTTP server."""
        dashboard = self

        class DashboardHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/" or self.path == "/index.html":
                    self._serve_index()
                elif self.path == "/api/jobs":
                    self._serve_jobs()
                elif self.path.startswith("/api/jobs/"):
                    job_id = self.path.split("/")[-1]
                    self._serve_job_details(job_id)
                elif self.path == "/api/status":
                    self._serve_status()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _serve_index(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(dashboard._index_html().encode("utf-8"))

            def _serve_jobs(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(dashboard.get_jobs()).encode("utf-8"))

            def _serve_job_details(self, job_id: str) -> None:
                job = dashboard.get_job_details(job_id)
                if job:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(job).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def _serve_status(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                # Suppress default log messages
                pass

        self._server = http.server.HTTPServer((self.host, self.port), DashboardHandler)
        # A server bound to port 0 is given a free port by the operating
        # system. The test can then ask the server which one it got, instead
        # of taking a port, releasing it, and hoping nobody else takes it in
        # between.
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        if open_browser:
            import webbrowser

            webbrowser.open(f"http://{self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the dashboard server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def _index_html(self) -> str:
        """Return the dashboard HTML."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>movie-review-ai Job Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        h1 { color: #333; }
        .refresh-btn { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .refresh-btn:hover { background: #0056b3; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 20px; }
        .stat-card { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .stat-card h3 { font-size: 14px; color: #666; margin-bottom: 8px; }
        .stat-card .value { font-size: 28px; font-weight: bold; color: #333; }
        table { width: 100%; background: white; border-collapse: collapse; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; color: #333; }
        tr:hover { background: #f8f9fa; }
        .status { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; }
        .status-COMPLETED { background: #d4edda; color: #155724; }
        .status-FAILED { background: #f8d7da; color: #721c24; }
        .status-IN_PROGRESS, .status-INGESTING, .status-SCENES_READY, .status-TRANSCRIPT_READY,
        .status-VISUAL_ANALYSIS_READY, .status-CHARACTERS_READY, .status-EVENTS_READY,
        .status-STORY_READY, .status-REVIEW_PLAN_READY, .status-SCRIPT_READY,
        .status-SCRIPT_VERIFIED, .status-AUDIO_READY, .status-EDIT_PLAN_READY,
        .status-RENDERED, .status-QUALITY_CHECKED { background: #fff3cd; color: #856404; }
        .status-CREATED { background: #e2e3e5; color: #383d41; }
        .status-NEEDS_REVIEW { background: #d1ecf1; color: #0c5460; }
        .details-btn { padding: 4px 8px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .details-btn:hover { background: #5a6268; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center; }
        .modal.show { display: flex; }
        .modal-content { background: white; padding: 24px; border-radius: 8px; max-width: 800px; max-height: 80vh; overflow: auto; width: 90%; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .close-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: #666; }
        pre { background: #f8f9fa; padding: 16px; border-radius: 4px; overflow: auto; font-size: 13px; line-height: 1.5; }
        .last-updated { color: #666; font-size: 14px; }
        .artifact-list { margin-top: 16px; }
        .artifact-item { padding: 8px; background: #f8f9fa; margin: 4px 0; border-radius: 4px; font-family: monospace; font-size: 13px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>movie-review-ai Job Dashboard</h1>
            <div>
                <span class="last-updated" id="lastUpdated">Loading...</span>
                <button class="refresh-btn" onclick="loadJobs()">Refresh</button>
            </div>
        </header>
        
        <div class="stats" id="stats">
            <div class="stat-card"><h3>Total Jobs</h3><div class="value" id="totalJobs">-</div></div>
            <div class="stat-card"><h3>Completed</h3><div class="value" id="completedJobs">-</div></div>
            <div class="stat-card"><h3>Running</h3><div class="value" id="runningJobs">-</div></div>
            <div class="stat-card"><h3>Failed</h3><div class="value" id="failedJobs">-</div></div>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Job ID</th>
                    <th>Input File</th>
                    <th>Status</th>
                    <th>Stage</th>
                    <th>Retries</th>
                    <th>Created</th>
                    <th>Updated</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="jobTable"></tbody>
        </table>
    </div>
    
    <div class="modal" id="detailModal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modalTitle">Job Details</h2>
                <button class="close-btn" onclick="closeModal()">&times;</button>
            </div>
            <pre id="modalContent"></pre>
        </div>
    </div>
    
    <script>
        let jobs = [];
        
        async function loadJobs() {
            try {
                const response = await fetch('/api/jobs');
                jobs = await response.json();
                renderJobs(jobs);
                updateStats(jobs);
                document.getElementById('lastUpdated').textContent = 'Last updated: ' + new Date().toLocaleTimeString();
            } catch (e) {
                console.error('Failed to load jobs:', e);
                document.getElementById('lastUpdated').textContent = 'Error loading jobs';
            }
        }
        
        function renderJobs(jobs) {
            const tbody = document.getElementById('jobTable');
            tbody.innerHTML = jobs.map(job => `
                <tr onclick="showDetails('${job.job_id}')" style="cursor: pointer;">
                    <td>${job.job_id}</td>
                    <td>${job.input_file}</td>
                    <td><span class="status status-${job.status}">${job.status}</span></td>
                    <td>${job.failed_stage || job.status}</td>
                    <td>${job.retry_count || 0}</td>
                    <td>${new Date(job.created_at).toLocaleString()}</td>
                    <td>${new Date(job.updated_at).toLocaleString()}</td>
                    <td><button class="details-btn" onclick="event.stopPropagation(); showDetails('${job.job_id}')">Details</button></td>
                </tr>
            `).join('');
        }
        
        function updateStats(jobs) {
            document.getElementById('totalJobs').textContent = jobs.length;
            document.getElementById('completedJobs').textContent = jobs.filter(j => j.status === 'COMPLETED').length;
            document.getElementById('runningJobs').textContent = jobs.filter(j => !['COMPLETED', 'FAILED', 'NEEDS_REVIEW'].includes(j.status)).length;
            document.getElementById('failedJobs').textContent = jobs.filter(j => j.status === 'FAILED').length;
        }
        
        async function showDetails(jobId) {
            try {
                const response = await fetch(`/api/jobs/${jobId}`);
                const job = await response.json();
                document.getElementById('modalTitle').textContent = `Job: ${jobId}`;
                document.getElementById('modalContent').textContent = JSON.stringify(job, null, 2);
                document.getElementById('detailModal').classList.add('show');
            } catch (e) {
                console.error('Failed to load job details:', e);
            }
        }
        
        function closeModal() {
            document.getElementById('detailModal').classList.remove('show');
        }
        
        // Auto-refresh every 5 seconds
        setInterval(loadJobs, 5000);
        loadJobs();
        
        // Close modal on background click
        document.getElementById('detailModal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) closeModal();
        });
    </script>
</body>
</html>"""


def run_dashboard(
    host: str = "127.0.0.1",
    port: int = 8080,
    db_path: str | None = None,
    open_browser: bool = False,
) -> JobDashboard:
    """Convenience function to create and start a dashboard."""
    dashboard = JobDashboard(host, port, db_path)
    dashboard.start(open_browser)
    return dashboard
