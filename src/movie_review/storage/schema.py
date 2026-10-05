"""Versioned SQLite schema (T005).

V1 covers the T004 domain: jobs, movies, scenes, evidence, claims,
artifacts. Later tasks add their tables as new migration versions; existing
statements are append-only history and must not be edited.
"""

SCHEMA_VERSION = 2

MIGRATION_1 = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        input_file TEXT NOT NULL,
        status TEXT NOT NULL,
        failed_stage TEXT,
        error TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS movies (
        movie_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        file TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        duration_seconds REAL NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        fps REAL NOT NULL,
        video_codec TEXT NOT NULL,
        audio_codec TEXT,
        container TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenes (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        scene_id TEXT NOT NULL,
        start REAL NOT NULL,
        end REAL NOT NULL,
        duration REAL NOT NULL,
        shot_count INTEGER NOT NULL DEFAULT 0,
        cut_density REAL NOT NULL DEFAULT 0.0,
        motion_score REAL NOT NULL DEFAULT 0.0,
        brightness REAL NOT NULL DEFAULT 0.0,
        audio_energy REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (job_id, scene_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence (
        id TEXT NOT NULL,
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        source_id TEXT NOT NULL,
        start REAL,
        end REAL,
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        claim_id TEXT NOT NULL,
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        type TEXT NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (job_id, claim_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        stage TEXT NOT NULL,
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        output_hash TEXT,
        model TEXT,
        prompt_version TEXT
    )
    """,
]

MIGRATION_2 = [
    """
    CREATE TABLE IF NOT EXISTS transcript_segments (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        segment_id TEXT NOT NULL,
        start REAL NOT NULL,
        end REAL NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        language TEXT,
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, segment_id)
    )
    """,
]

MIGRATIONS: dict[int, list[str]] = {1: MIGRATION_1, 2: MIGRATION_2}
