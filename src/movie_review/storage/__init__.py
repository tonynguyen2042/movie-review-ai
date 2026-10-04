"""SQLite persistence (T005). Domain models stay pure; see repositories."""

from movie_review.storage.database import bootstrap, connect, get_schema_version, migrate

__all__ = ["bootstrap", "connect", "get_schema_version", "migrate"]
