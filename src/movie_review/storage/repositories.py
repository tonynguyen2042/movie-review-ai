"""Repositories mapping T004 domain models to SQLite rows (T005).

Ownership (``job_id``) is a persistence concern supplied per call, keeping
domain models pure. Writes are idempotent (upsert/replace); the jobs table
uses ``ON CONFLICT DO UPDATE`` so lifecycle re-saves never cascade-wipe
children. Foreign-key violations surface as :class:`sqlite3.IntegrityError`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from movie_review.domain import (
    Artifact,
    Character,
    CharacterMention,
    Claim,
    ClaimStatus,
    ClaimType,
    Event,
    EventType,
    Evidence,
    EvidenceType,
    Job,
    JobStatus,
    Location,
    ModelRun,
    Movie,
    MovieMetadata,
    Relationship,
    RelationType,
    Scene,
    SceneAnalysis,
    TranscriptSegment,
)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


# -- jobs -----------------------------------------------------------------


def save_job(conn: sqlite3.Connection, job: Job) -> None:
    # NOTE: UPDATE (not REPLACE) — replacing the parent row would fire
    # ON DELETE CASCADE and wipe the job's movies/scenes/evidence/claims.
    with conn:
        conn.execute(
            """
            INSERT INTO jobs
                (job_id, input_file, status, failed_stage, error,
                 retry_count, style, spoilers, target_seconds, output_dir,
                 keep_intermediates, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                input_file = excluded.input_file,
                status = excluded.status,
                failed_stage = excluded.failed_stage,
                error = excluded.error,
                retry_count = excluded.retry_count,
                style = excluded.style,
                spoilers = excluded.spoilers,
                target_seconds = excluded.target_seconds,
                output_dir = excluded.output_dir,
                keep_intermediates = excluded.keep_intermediates,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                job.job_id,
                job.input_file,
                job.status.value,
                job.failed_stage,
                job.error,
                job.retry_count,
                job.style,
                job.spoilers,
                job.target_seconds,
                job.output_dir,
                1 if job.keep_intermediates else 0,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )


def insert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Insert a job without overwriting an existing one.

    Returns True when the row was inserted, False when the id was already
    taken. Job id allocation checks for a free id and then inserts, which is
    not atomic: two concurrent runs on the same day could pick the same id,
    and an upsert would then overwrite the first job's input file and
    status -- silently moving the first job's artifacts to a different
    movie. `AGENTS.md` lists data corruption as a stop condition.
    """
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs
                (job_id, input_file, status, failed_stage, error,
                 retry_count, style, spoilers, target_seconds, output_dir,
                 keep_intermediates, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO NOTHING
            """,
            (
                job.job_id,
                job.input_file,
                job.status.value,
                job.failed_stage,
                job.error,
                job.retry_count,
                job.style,
                job.spoilers,
                job.target_seconds,
                job.output_dir,
                1 if job.keep_intermediates else 0,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
    return cursor.rowcount > 0


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
        style=row["style"] if row["style"] is not None else "youtube",
        spoilers=row["spoilers"] if row["spoilers"] is not None else "full",
        target_seconds=row["target_seconds"],
        output_dir=row["output_dir"],
        keep_intermediates=bool(row["keep_intermediates"])
        if "keep_intermediates" in row.keys()
        else False,
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


def delete_scenes(conn: sqlite3.Connection, job_id: str) -> int:
    """Remove a job's scene rows; returns how many were removed.

    The scene list for a job is the whole set, not an accumulation. Writing
    the new rows over the old ones leaves any scene that the new detection
    does not contain still in the table, with its old boundaries, so a
    re-run leaves a mix of two timelines. The stage clears the set before it
    writes it.
    """
    with conn:
        cursor = conn.execute("DELETE FROM scenes WHERE job_id = ?", (job_id,))
    return cursor.rowcount


def save_scene_analyses(
    conn: sqlite3.Connection, job_id: str, analyses: list[SceneAnalysis]
) -> None:
    """Persist many scene analyses in one transaction.

    The vision stage writes one row per scene -- about a thousand for a
    feature film -- and each write was its own committed transaction.
    """
    if not analyses:
        return
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO scene_analyses
                (job_id, scene_id, location, characters_json, actions_json,
                 objects_json, emotions_json, visual_events_json,
                 importance, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    job_id,
                    analysis.scene_id,
                    analysis.location,
                    json.dumps(analysis.characters),
                    json.dumps(analysis.actions),
                    json.dumps(analysis.objects),
                    json.dumps(analysis.emotions),
                    json.dumps(analysis.visual_events),
                    analysis.importance,
                    analysis.confidence,
                )
                for analysis in analyses
            ],
        )


def save_scene_analysis(conn: sqlite3.Connection, job_id: str, analysis: SceneAnalysis) -> None:
    """Persist one scene's visual analysis.

    Lists are stored as JSON text rather than a side table: they are only ever
    read whole, never queried by element, and keeping one row per scene means the
    downstream stages can join against it like any other scene record.
    """
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scene_analyses
                (job_id, scene_id, location, characters_json, actions_json,
                 objects_json, emotions_json, visual_events_json,
                 importance, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                analysis.scene_id,
                analysis.location,
                json.dumps(analysis.characters),
                json.dumps(analysis.actions),
                json.dumps(analysis.objects),
                json.dumps(analysis.emotions),
                json.dumps(analysis.visual_events),
                analysis.importance,
                analysis.confidence,
            ),
        )


def _row_to_scene_analysis(row: sqlite3.Row) -> SceneAnalysis:
    def _list(column: str) -> list[str]:
        raw = row[column]
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            # A column that cannot be read is treated as empty rather than
            # crashing the whole stage: the other fields are still usable, and
            # silently dropping one list is better than losing the analysis.
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    return SceneAnalysis(
        scene_id=row["scene_id"],
        location=row["location"],
        characters=_list("characters_json"),
        actions=_list("actions_json"),
        objects=_list("objects_json"),
        emotions=_list("emotions_json"),
        visual_events=_list("visual_events_json"),
        importance=row["importance"],
        confidence=row["confidence"],
    )


def list_scene_analyses(conn: sqlite3.Connection, job_id: str) -> list[SceneAnalysis]:
    """Every visual analysis for a job, ordered by scene.

    Ordered by scene rather than by rowid so downstream stages see the analyses
    in the same order as the scene timeline they came from.
    """
    rows = conn.execute(
        "SELECT * FROM scene_analyses WHERE job_id = ? ORDER BY scene_id",
        (job_id,),
    ).fetchall()
    return [_row_to_scene_analysis(row) for row in rows]


def get_scene_analysis(
    conn: sqlite3.Connection, job_id: str, scene_id: str
) -> SceneAnalysis | None:
    row = conn.execute(
        "SELECT * FROM scene_analyses WHERE job_id = ? AND scene_id = ?",
        (job_id, scene_id),
    ).fetchone()
    return _row_to_scene_analysis(row) if row is not None else None


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


# -- transcript -----------------------------------------------------------


def save_transcript_segments(
    conn: sqlite3.Connection, job_id: str, segments: list[TranscriptSegment]
) -> None:
    with conn:
        conn.execute("DELETE FROM transcript_segments WHERE job_id = ?", (job_id,))
        conn.executemany(
            """
            INSERT INTO transcript_segments
                (job_id, segment_id, start, end, text, language, confidence, speaker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    job_id,
                    segment.segment_id,
                    segment.start,
                    segment.end,
                    segment.text,
                    segment.language,
                    segment.confidence,
                    segment.speaker,
                )
                for segment in segments
            ],
        )


def list_transcript_segments(conn: sqlite3.Connection, job_id: str) -> list[TranscriptSegment]:
    rows = conn.execute(
        "SELECT * FROM transcript_segments WHERE job_id = ? ORDER BY start", (job_id,)
    ).fetchall()
    return [
        TranscriptSegment(
            segment_id=row["segment_id"],
            start=row["start"],
            end=row["end"],
            text=row["text"],
            language=row["language"],
            confidence=row["confidence"],
            speaker=row["speaker"] if "speaker" in row.keys() else None,
        )
        for row in rows
    ]


# -- characters -----------------------------------------------------------


def save_character(conn: sqlite3.Connection, job_id: str, character: Character) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO characters
                (job_id, id, name, aliases_json, gender,
                 first_seen, last_seen, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                character.id,
                character.name,
                json.dumps(character.aliases),
                character.gender,
                character.first_seen,
                character.last_seen,
                character.confidence,
            ),
        )


def _row_to_character(row: sqlite3.Row) -> Character:
    return Character(
        id=row["id"],
        name=row["name"],
        aliases=list(json.loads(row["aliases_json"])),
        gender=row["gender"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        confidence=row["confidence"],
    )


def get_character(conn: sqlite3.Connection, job_id: str, character_id: str) -> Character | None:
    row = conn.execute(
        "SELECT * FROM characters WHERE job_id = ? AND id = ?", (job_id, character_id)
    ).fetchone()
    return _row_to_character(row) if row is not None else None


def list_characters(conn: sqlite3.Connection, job_id: str) -> list[Character]:
    rows = conn.execute(
        "SELECT * FROM characters WHERE job_id = ? ORDER BY first_seen", (job_id,)
    ).fetchall()
    return [_row_to_character(row) for row in rows]


def save_mention(conn: sqlite3.Connection, job_id: str, mention: CharacterMention) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO character_mentions
                (job_id, mention, source_segment_id, timestamp, character_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                mention.mention,
                mention.source_segment_id,
                mention.timestamp,
                mention.character_id,
            ),
        )


def save_mentions(conn: sqlite3.Connection, job_id: str, mentions: list[CharacterMention]) -> None:
    """Persist many character mentions in one transaction.

    A mention is written once per (character, segment) pair -- about 15000
    times for a feature film -- and each write was its own committed
    transaction. One statement for the whole list turns that into one
    commit.
    """
    if not mentions:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO character_mentions
                (job_id, mention, source_segment_id, timestamp, character_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    job_id,
                    mention.mention,
                    mention.source_segment_id,
                    mention.timestamp,
                    mention.character_id,
                )
                for mention in mentions
            ],
        )


def list_mentions(conn: sqlite3.Connection, job_id: str) -> list[CharacterMention]:
    rows = conn.execute(
        "SELECT * FROM character_mentions WHERE job_id = ? ORDER BY timestamp", (job_id,)
    ).fetchall()
    return [
        CharacterMention(
            mention=row["mention"],
            source_segment_id=row["source_segment_id"],
            timestamp=row["timestamp"],
            character_id=row["character_id"],
        )
        for row in rows
    ]


# -- speakers -------------------------------------------------------------


def save_speaker_link(
    conn: sqlite3.Connection,
    job_id: str,
    speaker_id: str,
    character_id: str | None,
    confidence: float,
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO speakers (job_id, speaker_id, character_id, confidence)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id, speaker_id) DO UPDATE SET
                character_id = excluded.character_id,
                confidence = excluded.confidence
            """,
            (job_id, speaker_id, character_id, confidence),
        )


def list_speaker_links(
    conn: sqlite3.Connection, job_id: str
) -> list[tuple[str, str | None, float]]:
    rows = conn.execute(
        "SELECT speaker_id, character_id, confidence FROM speakers "
        "WHERE job_id = ? ORDER BY speaker_id",
        (job_id,),
    ).fetchall()
    return [(row["speaker_id"], row["character_id"], row["confidence"]) for row in rows]


# -- locations ------------------------------------------------------------


def save_location(conn: sqlite3.Connection, job_id: str, location: Location) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO locations (job_id, id, name, first_seen, last_seen, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, id) DO UPDATE SET
                name = excluded.name,
                first_seen = excluded.first_seen,
                last_seen = excluded.last_seen,
                confidence = excluded.confidence
            """,
            (
                job_id,
                location.id,
                location.name,
                location.first_seen,
                location.last_seen,
                location.confidence,
            ),
        )


def _row_to_location(row: sqlite3.Row) -> Location:
    return Location(
        id=row["id"],
        name=row["name"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        confidence=row["confidence"],
    )


def list_locations(conn: sqlite3.Connection, job_id: str) -> list[Location]:
    rows = conn.execute(
        "SELECT * FROM locations WHERE job_id = ? ORDER BY first_seen", (job_id,)
    ).fetchall()
    return [_row_to_location(row) for row in rows]


# -- events -----------------------------------------------------------------


def save_event(conn: sqlite3.Connection, job_id: str, event: Event) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO events
                (job_id, id, type, timestamp, characters_json, location,
                 description, importance, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, id) DO UPDATE SET
                type = excluded.type,
                timestamp = excluded.timestamp,
                characters_json = excluded.characters_json,
                location = excluded.location,
                description = excluded.description,
                importance = excluded.importance,
                evidence_json = excluded.evidence_json
            """,
            (
                job_id,
                event.id,
                event.type.value,
                event.timestamp,
                json.dumps(event.characters),
                event.location,
                event.description,
                event.importance,
                json.dumps(event.evidence),
            ),
        )


def save_events(conn: sqlite3.Connection, job_id: str, events: list[Event]) -> None:
    """Persist many events in one transaction.

    The events stage writes one row per event -- hundreds for a feature
    film -- and each write was its own committed transaction.
    """
    if not events:
        return
    with conn:
        conn.executemany(
            """
            INSERT INTO events
                (job_id, id, type, timestamp, characters_json, location,
                 description, importance, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, id) DO UPDATE SET
                type = excluded.type,
                timestamp = excluded.timestamp,
                characters_json = excluded.characters_json,
                location = excluded.location,
                description = excluded.description,
                importance = excluded.importance,
                evidence_json = excluded.evidence_json
            """,
            [
                (
                    job_id,
                    event.id,
                    event.type.value,
                    event.timestamp,
                    json.dumps(event.characters),
                    event.location,
                    event.description,
                    event.importance,
                    json.dumps(event.evidence),
                )
                for event in events
            ],
        )


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        type=EventType(row["type"]),
        timestamp=row["timestamp"],
        characters=list(json.loads(row["characters_json"])),
        location=row["location"],
        description=row["description"],
        importance=row["importance"],
        evidence=list(json.loads(row["evidence_json"])),
    )


def get_event(conn: sqlite3.Connection, job_id: str, event_id: str) -> Event | None:
    row = conn.execute(
        "SELECT * FROM events WHERE job_id = ? AND id = ?", (job_id, event_id)
    ).fetchone()
    return _row_to_event(row) if row is not None else None


def list_events(conn: sqlite3.Connection, job_id: str) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM events WHERE job_id = ? ORDER BY timestamp", (job_id,)
    ).fetchall()
    return [_row_to_event(row) for row in rows]


# -- relationships ----------------------------------------------------------


def save_relationship(conn: sqlite3.Connection, job_id: str, relationship: Relationship) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO relationships
                (job_id, subject, relation, object, evidence_json, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                relationship.subject,
                relationship.relation.value,
                relationship.object,
                json.dumps(relationship.evidence),
                relationship.confidence,
            ),
        )


def list_relationships(conn: sqlite3.Connection, job_id: str) -> list[Relationship]:
    rows = conn.execute("SELECT * FROM relationships WHERE job_id = ?", (job_id,)).fetchall()
    return [
        Relationship(
            subject=row["subject"],
            relation=RelationType(row["relation"]),
            object=row["object"],
            evidence=list(json.loads(row["evidence_json"])),
            confidence=row["confidence"],
        )
        for row in rows
    ]


# -- artifacts ------------------------------------------------------------


def save_artifact(conn: sqlite3.Connection, artifact: Artifact) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
                (artifact_id, job_id, stage, relative_path, version, created_at,
                 input_hash, output_hash, model, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.job_id,
                artifact.stage,
                artifact.relative_path,
                artifact.version,
                artifact.created_at.isoformat(),
                artifact.input_hash,
                artifact.output_hash,
                artifact.model,
                artifact.prompt_version,
            ),
        )


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    # A database from before schema 9 has no filename column at all, so the key
    # is probed rather than assumed; an old row then reads as "no filename",
    # which validation reports rather than guesses at.
    relative = row["relative_path"] if "relative_path" in row.keys() else None
    return Artifact(
        artifact_id=row["artifact_id"],
        job_id=row["job_id"],
        stage=row["stage"],
        relative_path=relative,
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


def save_model_run(conn: sqlite3.Connection, job_id: str, run: ModelRun) -> None:
    """Record one model invocation."""
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO model_runs
                (run_id, job_id, stage, model, runtime, prompt_hash,
                 prompt_version, input_tokens, output_tokens, duration_ms,
                 temperature, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                job_id,
                run.stage,
                run.model,
                run.runtime,
                run.prompt_hash,
                run.prompt_version,
                run.input_tokens,
                run.output_tokens,
                run.duration_ms,
                run.temperature,
                run.created_at.isoformat(),
            ),
        )


def list_model_runs(
    conn: sqlite3.Connection, job_id: str, stage: str | None = None
) -> list[ModelRun]:
    """The recorded model invocations of a job, oldest first."""
    if stage is None:
        rows = conn.execute(
            "SELECT * FROM model_runs WHERE job_id = ? ORDER BY created_at, run_id",
            (job_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM model_runs WHERE job_id = ? AND stage = ? ORDER BY created_at, run_id",
            (job_id, stage),
        ).fetchall()
    return [_row_to_model_run(row) for row in rows]


def _row_to_model_run(row: sqlite3.Row) -> ModelRun:
    return ModelRun(
        run_id=row["run_id"],
        job_id=row["job_id"],
        stage=row["stage"],
        model=row["model"],
        runtime=row["runtime"],
        prompt_hash=row["prompt_hash"] or "",
        prompt_version=row["prompt_version"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        duration_ms=row["duration_ms"],
        temperature=row["temperature"],
        created_at=_parse_dt(row["created_at"]),
    )


def delete_artifact(conn: sqlite3.Connection, artifact_id: str) -> bool:
    """Remove one artifact record; returns whether a row was removed.

    `--force` drops the record of what a stage produced, so the stage runs
    again and rewrites it.
    """
    with conn:
        cursor = conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
    return cursor.rowcount > 0
