"""Tests for ingest: column mapping + domain normalisation.

Run with: pytest -q   (from the lead-qualifier/ directory)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lead_qualifier.ingest import load_leads, normalize_domain  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("acme.com", "acme.com"),
        ("https://acme.com", "acme.com"),
        ("http://www.acme.com/about", "acme.com"),
        ("WWW.ACME.COM", "acme.com"),
        ("jane@acme.com", "acme.com"),
        ("acme.com:443", "acme.com"),
        ("not a domain", None),
        ("", None),
        ("ftp://x", None),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_forgiving_column_mapping(tmp_path: Path):
    # Unusual header names should still map.
    f = tmp_path / "leads.csv"
    pd.DataFrame({"Company URL": ["a.com", "b.com"], "Account Name": ["A", "B"]}).to_csv(f, index=False)
    report = load_leads(f)
    assert report.domain_column == "Company URL"
    assert report.name_column == "Account Name"
    assert {r.domain for r in report.rows} == {"a.com", "b.com"}


def test_dedupe_and_skip(tmp_path: Path):
    f = tmp_path / "leads.csv"
    pd.DataFrame({"domain": ["a.com", "a.com", "bad row", ""]}).to_csv(f, index=False)
    report = load_leads(f)
    assert [r.domain for r in report.rows] == ["a.com"]
    assert len(report.skipped) == 3  # dup + invalid + empty


def test_limit(tmp_path: Path):
    f = tmp_path / "leads.csv"
    pd.DataFrame({"domain": [f"c{i}.com" for i in range(10)]}).to_csv(f, index=False)
    report = load_leads(f, limit=3)
    assert len(report.rows) == 3


def test_missing_domain_column_raises(tmp_path: Path):
    f = tmp_path / "leads.csv"
    pd.DataFrame({"foo": ["x"], "bar": ["y"]}).to_csv(f, index=False)
    with pytest.raises(ValueError):
        load_leads(f)
