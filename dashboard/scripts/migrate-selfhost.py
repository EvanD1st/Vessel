"""Apply reviewed SQLite migrations to a dedicated Ubuntu dashboard database."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def migrate(database: Path, root: Path):
    if database.is_symlink() or not database.is_file():
        raise ValueError("The private dashboard database must already exist and be a regular file")
    database = database.resolve()
    with sqlite3.connect(database, timeout=5) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE IF NOT EXISTS vessel_local_migrations (name TEXT PRIMARY KEY, hash TEXT NOT NULL)")
        connection.commit()
        journal = json.loads((root / "drizzle/meta/_journal.json").read_text())
        for item in journal["entries"]:
            tag = item["tag"]
            if not tag.replace("_", "").isalnum():
                raise ValueError("Invalid migration name")
            content = (root / "drizzle" / (tag + ".sql")).read_text()
            checksum = hashlib.sha256(content.encode()).hexdigest()
            applied = connection.execute("SELECT hash FROM vessel_local_migrations WHERE name=?", (tag,)).fetchone()
            if applied:
                if applied[0] != checksum:
                    raise ValueError("Previously applied migration changed: " + tag)
                continue
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in content.split("--> statement-breakpoint"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("INSERT INTO vessel_local_migrations VALUES (?,?)", (tag, checksum))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            print("Applied dashboard migration:", tag)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    migrate(args.database, Path(__file__).resolve().parents[1])
