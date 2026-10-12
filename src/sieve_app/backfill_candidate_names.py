"""Recover names from legacy local resumes without adding identity to ranking evidence."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import psycopg

from talent_ranker.config import SETTINGS
from talent_ranker.documents import extract_resume

from .resume_identity import corroborated_name, extract_identity


def backfill(*, apply: bool = False) -> tuple[int, int, int, int]:
    """Recheck legacy names; accept only those corroborated by the artifact."""
    found = review = failed = withdrawn = 0
    with psycopg.connect(SETTINGS.database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.candidate_id,c.source_uri,c.source_sha256,n.display_name
               FROM candidates c LEFT JOIN candidate_names n ON n.candidate_id=c.candidate_id
               WHERE c.deleted_at IS NULL
                 AND (n.candidate_id IS NULL OR n.source='legacy_resume_header')"""
        )
        for candidate_id, source_uri, source_sha256, previous_name in cur.fetchall():
            try:
                parsed = urlparse(source_uri)
                if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                    review += 1
                    continue
                path = Path(url2pathname(parsed.path))
                if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha256:
                    raise ValueError("source hash changed")
                identity = extract_identity(extract_resume(path))
                if identity.name and corroborated_name(identity.name, path.stem, identity.email):
                    found += 1
                    if not apply:
                        continue
                    cur.execute(
                        """INSERT INTO candidate_names(candidate_id,display_name,source)
                           VALUES (%s,%s,'legacy_resume_header')
                           ON CONFLICT(candidate_id) DO UPDATE SET
                             display_name=excluded.display_name,updated_at=now()
                           WHERE candidate_names.source='legacy_resume_header'""",
                        (candidate_id, identity.name),
                    )
                else:
                    review += 1
                    if previous_name:
                        withdrawn += 1
                        if apply:
                            cur.execute(
                                "DELETE FROM candidate_names WHERE candidate_id=%s AND source='legacy_resume_header'",
                                (candidate_id,),
                            )
            except (OSError, ValueError):
                failed += 1
                if previous_name:
                    withdrawn += 1
                    if apply:
                        cur.execute(
                            "DELETE FROM candidate_names WHERE candidate_id=%s AND source='legacy_resume_header'",
                            (candidate_id,),
                        )
    return found, review, failed, withdrawn


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill protected candidate names from local resumes")
    parser.add_argument("--apply", action="store_true", help="Write extracted names; default is dry run")
    args = parser.parse_args()
    found, review, failed, withdrawn = backfill(apply=args.apply)
    print(f"Corroborated: {found}; needs review: {review}; extraction failures: {failed}; "
          f"legacy names {'removed' if args.apply else 'to remove'}: {withdrawn}")


if __name__ == "__main__":
    main()
