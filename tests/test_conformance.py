"""Offline conformance of the exporter against the VENDORED signal-export
contract (tests/vendor/signal-export/). Two checks:

1. The vendored test vectors themselves validate as documented: every
   `valid*` vector passes the schema, every `invalid-*` vector fails it. This
   pins the vendored schema copy against the upstream contract's own examples.
2. A live exporter payload (built by cerebro/sink/export.signal_to_payload from
   a vault-note-shaped Signal) validates against the same schema and reproduces
   the fingerprint baked into `valid.json`, proving cerebro's vendored
   canonicalization is byte-identical to the contract's, so fingerprints agree
   on both sides of the ingest seam.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from cerebro.models import Signal
from cerebro.sink import export

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402

VENDOR = pathlib.Path(__file__).resolve().parent / "vendor" / "signal-export"
RESEARCH_SIGNAL_SCHEMA = json.loads(
    (VENDOR / "schemas" / "research-signal.schema.json").read_text()
)
TRIED_LEDGER_SCHEMA = json.loads(
    (VENDOR / "schemas" / "tried-ledger-entry.schema.json").read_text()
)


def _vectors(kind: str):
    return sorted((VENDOR / "test-vectors" / kind).glob("*.json"))


def _schema_for(kind: str):
    return RESEARCH_SIGNAL_SCHEMA if kind == "research-signal" else TRIED_LEDGER_SCHEMA


@pytest.mark.parametrize(
    "vector",
    _vectors("research-signal") + _vectors("tried-ledger-entry"),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_vendored_vectors_validate_as_labelled(vector):
    kind = vector.parent.name
    validator = Draft202012Validator(_schema_for(kind))
    payload = json.loads(vector.read_text())
    errors = list(validator.iter_errors(payload))
    if vector.name.startswith("invalid-"):
        assert errors, f"{vector.name} was expected to FAIL schema validation"
    else:
        assert not errors, f"{vector.name} should PASS but failed: {[e.message for e in errors]}"


def test_exporter_output_validates_against_schema():
    signal = Signal(
        url="https://github.com/UKGovernmentBEIS/inspect_ai",
        title="Inspect AI is trending",
        source="github_trending",
        url_hash="deadbeefcafef00d",
        clean_text="Inspect AI adds new scorers.",
        simhash=4611686018427387900,
        score=0.85,
        category="coding-agents",
        tags=["evals", "inspect"],
        captured="2026-07-16T09:00:00Z",
        meta={"reason": "eval-authoring guidance is behind upstream"},
    )
    payload = export.signal_to_payload(signal, "meridian", run_id="cerebro-2026-07-16")
    Draft202012Validator(RESEARCH_SIGNAL_SCHEMA).validate(payload)   # raises on any violation


def test_exporter_fingerprint_matches_contract_vector():
    """The url in valid.json fingerprints to the value baked into that vector.
    If cerebro's vendored canonicalization ever drifts from the contract, this
    fails instead of silently poisoning the ledger keyspace."""
    valid = json.loads((VENDOR / "test-vectors" / "research-signal" / "valid.json").read_text())
    assert export.fingerprint_url(valid["url"]) == valid["fingerprint"]


def test_all_signal_sources_are_accepted_by_schema():
    """Every source cerebro can emit is in the schema's accepted enum (an unknown
    source is a hard reject downstream)."""
    enum = set(RESEARCH_SIGNAL_SCHEMA["properties"]["source"]["enum"])
    assert set(export.SIGNAL_SOURCES) == enum
