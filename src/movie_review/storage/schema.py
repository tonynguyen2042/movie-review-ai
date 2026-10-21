"""Versioned SQLite schema (T005).

V1 covers the T004 domain: jobs, movies, scenes, evidence, claims,
artifacts. Later tasks add their tables as new migration versions; existing
statements are append-only history and must not be edited.
"""

SCHEMA_VERSION = 12

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

MIGRATION_3 = [
    """
    CREATE TABLE IF NOT EXISTS characters (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        aliases_json TEXT NOT NULL DEFAULT '[]',
        gender TEXT NOT NULL DEFAULT 'unknown',
        first_seen REAL NOT NULL,
        last_seen REAL NOT NULL,
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS character_mentions (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        mention TEXT NOT NULL,
        source_segment_id TEXT NOT NULL,
        timestamp REAL NOT NULL,
        character_id TEXT
    )
    """,
]

MIGRATION_4 = [
    """
    CREATE TABLE IF NOT EXISTS speakers (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        speaker_id TEXT NOT NULL,
        character_id TEXT,
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, speaker_id)
    )
    """,
]

MIGRATION_5 = [
    """
    CREATE TABLE IF NOT EXISTS locations (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        first_seen REAL NOT NULL,
        last_seen REAL NOT NULL,
        confidence REAL NOT NULL,
        PRIMARY KEY (job_id, id)
    )
    """,
]

MIGRATION_6 = [
    """
    CREATE TABLE IF NOT EXISTS events (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        id TEXT NOT NULL,
        type TEXT NOT NULL,
        timestamp REAL NOT NULL,
        characters_json TEXT NOT NULL DEFAULT '[]',
        location TEXT,
        description TEXT NOT NULL,
        importance REAL NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (job_id, id)
    )
    """,
]

MIGRATION_7 = [
    """
    CREATE TABLE IF NOT EXISTS relationships (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        subject TEXT NOT NULL,
        relation TEXT NOT NULL,
        object TEXT NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL
    )
    """,
]

MIGRATION_8 = [
    """
    CREATE TABLE IF NOT EXISTS scene_analyses (
        job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        scene_id TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        characters_json TEXT NOT NULL DEFAULT '[]',
        actions_json TEXT NOT NULL DEFAULT '[]',
        objects_json TEXT NOT NULL DEFAULT '[]',
        emotions_json TEXT NOT NULL DEFAULT '[]',
        visual_events_json TEXT NOT NULL DEFAULT '[]',
        importance REAL NOT NULL DEFAULT 0.5,
        confidence REAL NOT NULL DEFAULT 1.0,
        PRIMARY KEY (job_id, scene_id)
    )
    """
]

MIGRATION_9 = [
    # Added so validation can locate a file from its row instead of guessing a
    # filename from the job status. ALTER rather than a new table: the existing
    # rows are the provenance record, and migrate() applies each version once
    # (tracked by user_version), so this is not re-run on the same database.
    """
    ALTER TABLE artifacts ADD COLUMN relative_path TEXT
    """,
]

MIGRATION_10 = [
    # The review options the operator chose when the job was accepted. They
    # used to be logged and then discarded, so `--duration 5m --style
    # documentary` produced a 20-minute youtube-style review and reported
    # success. The job row is the only place that survives a resume, so the
    # options have to live there.
    """
    ALTER TABLE jobs ADD COLUMN style TEXT NOT NULL DEFAULT 'youtube'
    """,
    """
    ALTER TABLE jobs ADD COLUMN spoilers TEXT NOT NULL DEFAULT 'full'
    """,
    """
    ALTER TABLE jobs ADD COLUMN target_seconds REAL
    """,
    """
    ALTER TABLE jobs ADD COLUMN output_dir TEXT
    """,
]

MIGRATION_11 = [
    # The three tables that grow per job and are read back per job. Without
    # an index, listing a job's mentions or relationships was a full table
    # scan of every job's rows. `character_mentions` is written once per
    # (character, segment) pair -- about 15000 times for a feature film --
    # and the artifacts table is read on every validation.
    """
    CREATE INDEX IF NOT EXISTS idx_mentions_job
        ON character_mentions (job_id, timestamp)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_relationships_job
        ON relationships (job_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_job
        ON artifacts (job_id)
    """,
]

MIGRATION_12 = [
    # The diarization stage records which speaker said each line. The
    # speakers table was always empty, so the transcript carried no
    # attribution and the speaker-to-character linking had nothing to
    # resolve.
    """
    ALTER TABLE transcript_segments ADD COLUMN speaker TEXT
    """,
]

MIGRATIONS: dict[int, list[str]] = {
    1: MIGRATION_1,
    2: MIGRATION_2,
    3: MIGRATION_3,
    4: MIGRATION_4,
    5: MIGRATION_5,
    6: MIGRATION_6,
    7: MIGRATION_7,
    8: MIGRATION_8,
    9: MIGRATION_9,
    10: MIGRATION_10,
    11: MIGRATION_11,
    12: MIGRATION_12,
}
