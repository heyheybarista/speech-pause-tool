"""Small, startup-safe SQLite migrations that preserve existing data."""

from pathlib import Path
import sqlite3


def migrate_annotation_targets(database_path: str) -> bool:
    """Remove the legacy one-target-per-utterance constraint.

    Returns True when the database schema was changed. The original database
    is copied once next to the live file before the table-rebuild migration.
    """
    db_path = Path(database_path)
    if not db_path.exists():
        return False

    connection = sqlite3.connect(str(db_path), timeout=30)
    try:
        columns = connection.execute(
            "PRAGMA table_info(annotation_targets)"
        ).fetchall()
        if not columns:
            return False

        column_names = {row[1] for row in columns}
        unique_indexes = [
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(annotation_targets)"
            ).fetchall()
            if row[2]
        ]
        has_utterance_unique = any(
            [row[2] for row in connection.execute(
                f'PRAGMA index_info("{name.replace(chr(34), chr(34) * 2)}")'
            ).fetchall()] == ["utterance_id"]
            for name in unique_indexes
        )

        if not has_utterance_unique:
            if "target_index" not in column_names:
                connection.execute(
                    "ALTER TABLE annotation_targets "
                    "ADD COLUMN target_index INTEGER NOT NULL DEFAULT 0"
                )
                connection.commit()
                return True
            return False

        connection.execute("PRAGMA wal_checkpoint(FULL)")
        backup_path = db_path.with_name(
            db_path.name + ".pre_multi_pause.bak"
        )
        if not backup_path.exists():
            backup_connection = sqlite3.connect(str(backup_path), timeout=30)
            try:
                connection.backup(backup_connection)
            finally:
                backup_connection.close()

        target_index_expr = (
            "COALESCE(target_index, 0)"
            if "target_index" in column_names
            else "0"
        )
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                CREATE TABLE annotation_targets_new (
                    id VARCHAR(24) NOT NULL,
                    session_id VARCHAR(24) NOT NULL,
                    utterance_id VARCHAR(24) NOT NULL,
                    target_index INTEGER NOT NULL DEFAULT 0,
                    label VARCHAR(20) NOT NULL,
                    required BOOLEAN,
                    display_hint VARCHAR(64),
                    pause_duration_ms INTEGER,
                    PRIMARY KEY (id),
                    FOREIGN KEY(session_id) REFERENCES sessions (id),
                    FOREIGN KEY(utterance_id) REFERENCES utterances (id)
                )
                """
            )
            connection.execute(
                f"""
                INSERT INTO annotation_targets_new
                    (id, session_id, utterance_id, target_index, label,
                     required, display_hint, pause_duration_ms)
                SELECT id, session_id, utterance_id, {target_index_expr}, label,
                       required, display_hint, pause_duration_ms
                FROM annotation_targets
                """
            )
            connection.execute("DROP TABLE annotation_targets")
            connection.execute(
                "ALTER TABLE annotation_targets_new RENAME TO annotation_targets"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys=ON")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Foreign key violations after annotation target migration: {violations}"
            )
        return True
    finally:
        connection.close()


def migrate_annotation_categories(database_path: str) -> bool:
    """Add multi-reason storage while preserving the legacy category column."""
    db_path = Path(database_path)
    if not db_path.exists():
        return False

    connection = sqlite3.connect(str(db_path), timeout=30)
    try:
        columns = connection.execute("PRAGMA table_info(annotations)").fetchall()
        if not columns:
            return False
        if "categories" in {row[1] for row in columns}:
            return False

        connection.execute("ALTER TABLE annotations ADD COLUMN categories JSON")
        connection.commit()
        return True
    finally:
        connection.close()
