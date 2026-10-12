"""Transactional recruiter confirmation and candidate ID reservation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from talent_ranker.identifiers import format_candidate_id, validate_candidate_id

from .resume_identity import EMAIL


class IdentityApprovalMixin:
    def approve(
        self, job_id: UUID, actor: str, decisions: list[dict[str, str | None]]
    ) -> dict[str, Any]:
        with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM sharepoint_ingestion_jobs
                   WHERE id=%s AND created_by=%s FOR UPDATE""", (job_id, actor),
            )
            job = cur.fetchone()
            if job is None:
                raise LookupError("indexing job not found")
            if job["status"] != "awaiting_review" or job["phase"] != "analyze":
                raise ValueError("job is not awaiting review")
            proposals = {item["object_id"]: item for item in job["entries"]}
            selected = {item["object_id"]: item for item in decisions}
            if len(selected) != len(decisions) or proposals.keys() != selected.keys():
                raise ValueError("review must decide every file exactly once")
            cur.execute("SELECT pg_advisory_xact_lock(77299001)")
            cur.execute(
                """SELECT greatest(
                     coalesce((SELECT max(substring(candidate_id from 6)::integer)
                               FROM candidates WHERE candidate_id ~ '^CAND_[0-9]{4}$'),0),
                     coalesce((SELECT max(candidate_number) FROM candidate_id_allocations),0)
                   ) AS highest"""
            )
            next_number = cur.fetchone()["highest"]
            entries = []
            used_ids = set()
            new_emails = set()
            new_hashes = set()
            for object_id, proposal in proposals.items():
                decision = selected[object_id]
                action = decision["action"]
                if action == "skip":
                    continue
                if action == "existing":
                    candidate_id = validate_candidate_id(decision.get("candidate_id") or "")
                    if proposal.get("locked_conflict"):
                        raise ValueError("conflicting exact file matches require manual resolution")
                    if proposal.get("locked_candidate_id") and (
                        candidate_id != proposal["locked_candidate_id"]
                    ):
                        raise ValueError("an exact file match cannot be reassigned")
                    cur.execute(
                        "SELECT 1 FROM candidates WHERE candidate_id=%s AND deleted_at IS NULL",
                        (candidate_id,),
                    )
                    if cur.fetchone() is None:
                        raise ValueError(f"{candidate_id} does not exist")
                    if proposal["suggestion"] == "existing" and (
                        proposal["candidate_id"] != candidate_id
                    ):
                        raise ValueError("suggested identity differs; resolve the conflict first")
                elif action == "new":
                    if proposal["suggestion"] != "new" or proposal.get("analysis_error"):
                        raise ValueError("a matched file cannot create a new candidate")
                    next_number += 1
                    candidate_id = format_candidate_id(next_number)
                    cur.execute(
                        "INSERT INTO candidate_id_allocations(candidate_number,job_id) VALUES (%s,%s)",
                        (next_number, job_id),
                    )
                else:
                    raise ValueError("invalid review action")
                if candidate_id in used_ids:
                    raise ValueError("one candidate cannot be indexed from two files in one job")
                used_ids.add(candidate_id)
                name = (decision.get("name") or "").strip()[:120]
                email = (decision.get("email") or "").strip().casefold()
                if email and (len(email) > 320 or not EMAIL.fullmatch(email)):
                    raise ValueError("reviewed email address is invalid")
                if action == "existing" and email:
                    cur.execute(
                        "SELECT lower(email) AS email FROM screening_contacts WHERE candidate_id=%s",
                        (candidate_id,),
                    )
                    contact = cur.fetchone()
                    if contact and contact["email"] != email:
                        raise ValueError("existing contact email differs; update it in contact review")
                if action == "new" and email:
                    if email in new_emails:
                        raise ValueError("two new files have the same email")
                    new_emails.add(email)
                    cur.execute(
                        "SELECT 1 FROM screening_contacts WHERE lower(email)=%s LIMIT 1",
                        (email,),
                    )
                    if cur.fetchone() is not None:
                        raise ValueError("email already belongs to a candidate; review the match")
                if action == "new":
                    if proposal["sha256"] in new_hashes:
                        raise ValueError("two new resumes have identical content")
                    new_hashes.add(proposal["sha256"])
                entries.append({"object_id": object_id, "candidate_id": candidate_id,
                                "name": name, "email": email,
                                "job_title": (decision.get("job_title") or "").strip()[:120],
                                "sha256": proposal["sha256"]})
            if not entries:
                raise ValueError("select at least one resume to index")
            cur.execute(
                """UPDATE sharepoint_ingestion_jobs SET entries=%s,phase='index',status='pending',
                      discovered=0,updated_at=now() WHERE id=%s RETURNING *""",
                (Jsonb(entries), job_id),
            )
            return cur.fetchone()
