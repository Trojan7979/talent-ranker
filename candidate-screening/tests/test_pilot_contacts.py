import json
from pathlib import Path

import pytest

from scripts.load_pilot_contacts import load_manifest


def test_pilot_manifest_requires_four_distinct_real_recipients(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples" / "pilot-contacts.example.json"
    contacts = json.loads(example.read_text(encoding="utf-8"))
    file = tmp_path / "contacts.json"
    file.write_text(json.dumps(contacts), encoding="utf-8")
    with pytest.raises(ValueError, match="replace example"):
        load_manifest(file)

    contacts[0]["email"] = "first@gmail.com"
    contacts[1]["email"] = "second@gmail.com"
    contacts[2]["email"] = "first@outlook.com"
    contacts[3]["email"] = "second@outlook.com"
    file.write_text(json.dumps(contacts), encoding="utf-8")
    assert len(load_manifest(file)) == 4

    contacts[3]["email"] = contacts[2]["email"]
    file.write_text(json.dumps(contacts), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_manifest(file)
