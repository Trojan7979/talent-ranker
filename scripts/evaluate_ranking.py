"""Evaluate one saved run against recruiter-reviewed binary labels."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from talent_ranker.config import SETTINGS
from talent_ranker.evaluation import evaluate_run
from talent_ranker.repository import PostgresRepository


def read_labels(path: Path) -> dict[str, bool]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"candidate_id", "relevant"} <= set(reader.fieldnames):
            raise ValueError("labels CSV needs candidate_id and relevant columns")
        labels = {}
        for row in reader:
            value = row["relevant"].strip()
            if value not in {"0", "1"}:
                raise ValueError("relevant must be 0 or 1")
            labels[row["candidate_id"].strip()] = value == "1"
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be positive")
    repo = PostgresRepository(SETTINGS.database_url)
    try:
        with repo.conn.cursor() as cursor:
            cursor.execute(
                "SELECT scoring_config FROM ranking_runs WHERE run_id = %s::uuid",
                (args.run_id,),
            )
            run = cursor.fetchone()
            if run is None:
                parser.error("ranking run not found")
            cursor.execute(
                """SELECT candidate_id, requirement_evidence FROM ranking_results
                   WHERE run_id = %s::uuid ORDER BY rank""",
                (args.run_id,),
            )
            ranked = [
                {"candidate_id": cid, "requirement_evidence": evidence}
                for cid, evidence in cursor.fetchall()
            ]
        config = run[0]
        if "retrieval_trace" not in config:
            parser.error("run predates retrieval tracing")
        report = evaluate_run(
            read_labels(args.labels),
            config["retrieval_trace"],
            config["shortlist_ids"],
            ranked,
            args.k,
        )
        print(json.dumps(report, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
