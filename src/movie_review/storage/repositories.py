"""Repositories mapping T004 domain models to SQLite rows (T005).

Ownership (``job_id``) is a persistence concern supplied per call, keeping
domain models pure. All writes use ``INSERT OR REPLACE`` so stage reruns are
idempotent; foreign-key violations surface as :class:`sqlite3.IntegrityError`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from movie_review.domain import (
    Artifact,
    Claim,
    ClaimStatus,
    ClaimType,
    Evidence,
    EvidenceType,
    Job,
    JobStatus,
    Movie,
    MovieMetadata,
    Scene,
)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


# -- jobs -----------------------------------------------------------------


def save_job(conn: sqlite3.Connection, job: Job) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs
                (job_id, input_file, status, failed_stage, error,
                 retry_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.input_file,
                job.status.value,
                job.failed_stage,
                job.error,
                job.retry_count,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return Job(
        job_id=row["job_id"],
        input_file=row["input_file"],
        status=JobStatus(row["status"]),
        failed_stage=row["failed_stage"],
        error=row["error"],
        retry_count=row["retry_count"],
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


# -- movies ---------------------------------------------------------------


def save_movie(conn: sqlite3.Connection, job_id: str, movie: Movie) -> None:
    meta = movie.metadata
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO movies
                (movie_id, job_id, file, sha256, duration_seconds, width,
                 height, fps, video_codec, audio_codec, container)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                movie.id,
                job_id,
                meta.file,
                meta.sha256,
                meta.duration_seconds,
                meta.width,
                meta.height,
                meta.fps,
                meta.video_codec,
                meta.audio_codec,
                meta.container,
            ),
        )


def get_movie(conn: sqlite3.Connection, job_id: str) -> Movie | None:
    row = conn.execute("SELECT * FROM movies WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return Movie(
        id=row["movie_id"],
        metadata=MovieMetadata(
            file=row["file"],
            sha256=row["sha256"],
            duration_seconds=row["duration_seconds"],
            width=row["width"],
            height=row["height"],
            fps=row["fps"],
            video_codec=row["video_codec"],
            audio_codec=row["audio_codec"],
            container=row["container"],
        ),
    )


# -- scenes ---------------------------------------------------------------


def save_scene(conn: sqlite3.Connection, job_id: str, scene: Scene) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scenes
                (job_id, scene_id, start, end, duration, shot_count,
                 cut_density, motion_score, brightness, audio_energy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                scene.scene_id,
                scene.start,
                scene.end,
                scene.duration,
                scene.shot_count,
                scene.cut_density,
                scene.motion_score,
                scene.brightness,
                scene.audio_energy,
            ),
        )


def _row_to_scene(row: sqlite3.Row) -> Scene:
    return Scene(
        scene_id=row["scene_id"],
        start=row["start"],
        end=row["end"],
        duration=row["duration"],
        shot_count=row["shot_count"],
        cut_density=row["cut_density"],
        motion_score=row["motion_score"],
        brightness=row["brightness"],
        audio_energy=row["audio_energy"],
    )


def get_scene(conn: sqlite3.Connection, job_id: str, scene_id: str) -> Scene | None:
    row = conn.execute(
        "SELECT * FROM scenes WHERE job_id = ? AND scene_id = ?", (job_id, scene_id)
    ).fetchone()
    return _row_to_scene(row) if row is not None else None


def list_scenes(conn: sqlite3.Connection, job_id: str) -> list[Scene]:
    rows = conn.execute(
        "SELECT * FROM scenes WHERE job_id = ? ORDER BY start", (job_id,)
    ).fetchall()
    return [_row_to_scene(row) for row in rows]


# -- evidence -------------------------------------------------------------


def save_evidence(conn: sqlite3.Connection, job_id: str, evidence: Evidence) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence
                (id, job_id, type, source_id, start, end, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                job_id,
                evidence.type.value,
                evidence.source_id,
                evidence.start,
                evidence.end,
                evidence.confidence,
            ),
        )


def list_evidence(
    conn: sqlite3.Connection, job_id: str, type: EvidenceType | None = None
) -> list[Evidence]:
    if type is None:
        rows = conn.execute("SELECT * FROM evidence WHERE job_id = ?", (job_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM evidence WHERE job_id = ? AND type = ?",
            (job_id, type.value),
        ).fetchall()
    return [
        Evidence(
            id=row["id"],
            type=EvidenceType(row["type"]),
            source_id=row["source_id"],
            start=row["start"],
            end=row["end"],
            confidence=row["confidence"],
        )
        for row in rows
    ]


# -- claims ---------------------------------------------------------------


def save_claim(conn: sqlite3.Connection, job_id: str, claim: Claim) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO claims
                (claim_id, job_id, text, type, evidence_json, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_id,
                job_id,
                claim.text,
                claim.type.value,
                json.dumps(claim.evidence),
                claim.confidence,
                claim.status.value,
            ),
        )


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        claim_id=row["claim_id"],
        text=row["text"],
        type=ClaimType(row["type"]),
        evidence=list(json.loads(row["evidence_json"])),
        confidence=row["confidence"],
        status=ClaimStatus(row["status"]),
    )


def get_claim(conn: sqlite3.Connection, job_id: str, claim_id: str) -> Claim | None:
    row = conn.execute(
        "SELECT * FROM claims WHERE job_id = ? AND claim_id = ?", (job_id, claim_id)
    ).fetchone()
    return _row_to_claim(row) if row is not None else None


def list_claims(conn: sqlite3.Connection, job_id: str) -> list[Claim]:
    rows = conn.execute("SELECT * FROM claims WHERE job_id = ?", (job_id,)).fetchall()
    return [_row_to_claim(row) for row in rows]


# -- artifacts ------------------------------------------------------------


def save_artifact(conn: sqlite3.Connection, artifact: Artifact) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
                (artifact_id, job_id, stage, version, created_at,
                 input_hash, output_hash, model, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.job_id,
                artifact.stage,
                artifact.version,
                artifact.created_at.isoformat(),
                artifact.input_hash,
                artifact.output_hash,
                artifact.model,
                artifact.prompt_version,
            ),
        )


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        artifact_id=row["artifact_id"],
        job_id=row["job_id"],
        stage=row["stage"],
        version=row["version"],
        created_at=_parse_dt(row["created_at"]),
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        model=row["model"],
        prompt_version=row["prompt_version"],
    )


def get_artifact(conn: sqlite3.Connection, artifact_id: str) -> Artifact | None:
    row = conn.execute("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
    return _row_to_artifact(row) if row is not None else None


def list_artifacts(
    conn: sqlite3.Connection, job_id: str, stage: str | None = None
) -> list[Artifact]:
    if stage is None:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE job_id = ? ORDER BY version", (job_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE job_id = ? AND stage = ? ORDER BY version",
            (job_id, stage),
        ).fetchall()
    return [_row_to_artifact(row) for row in rows]
