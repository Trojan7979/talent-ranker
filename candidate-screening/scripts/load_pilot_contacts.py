"""Load four pilot recipients through the protected screening contact API."""

import argparse
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


def load_manifest(path: Path) -> list[dict[str, str]]:
    contacts = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contacts, list) or len(contacts) != 4:
        raise ValueError("pilot manifest must contain exactly four contacts")
    if Counter(row.get("provider") for row in contacts) != {"gmail": 2, "outlook": 2}:
        raise ValueError("pilot needs two Gmail and two Outlook recipients")
    ids = [row["candidate_id"] for row in contacts]
    emails = [row["email"].strip().casefold() for row in contacts]
    if len(set(ids)) != 4 or len(set(emails)) != 4:
        raise ValueError("candidate IDs and email addresses must be unique")
    if any(email.endswith(".invalid") for email in emails):
        raise ValueError("replace example addresses before loading real contacts")
    return contacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare four pilot screening contacts")
    parser.add_argument("--file", type=Path, default=Path("secrets/pilot-contacts.json"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8001")
    parser.add_argument("--apply", action="store_true", help="write contacts through the API")
    args = parser.parse_args()
    contacts = load_manifest(args.file)
    for row in contacts:
        print(f"{row['candidate_id']}: {row['provider']} recipient")
    if not args.apply:
        print("Preview only. Pass --apply to configure these contacts.")
        return
    bearer = os.getenv("SCREENING_RECRUITER_TOKEN")
    if not bearer:
        parser.error("SCREENING_RECRUITER_TOKEN is required for --apply")
    for row in contacts:
        data = json.dumps(
            {"email": row["email"], "source": "four-inbox-pilot", "contactable": True}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{args.api_url.rstrip('/')}/screening/candidates/{row['candidate_id']}/contact",
            data=data,
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError(
                        f"contact {row['candidate_id']} returned HTTP {response.status}"
                    )
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"contact {row['candidate_id']} rejected with HTTP {error.code}"
            ) from error
    print("Four pilot contacts configured; no email was sent.")


if __name__ == "__main__":
    main()
