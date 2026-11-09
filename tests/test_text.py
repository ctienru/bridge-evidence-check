from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bridge_check.text import locate, quote_sha256, read_doc, sha8, sha256_hex


def test_locate_zero_one_two_hits() -> None:
    doc = "Weight 96 kg today. Weight 96 kg last visit. Height 170 cm."
    assert locate(doc, "no such text") == []
    assert locate(doc, "Height 170 cm") == [(45, 58)]
    hits = locate(doc, "Weight 96 kg")
    assert hits == [(0, 12), (20, 32)]
    assert all(doc[s:e] == "Weight 96 kg" for s, e in hits)


def test_locate_is_exact_not_normalized() -> None:
    assert locate("BMI 41.2", "bmi 41.2") == []
    assert locate("BMI  41.2", "BMI 41.2") == []
    assert locate("abc", "") == []


def test_locate_reports_overlapping_hits() -> None:
    assert locate("aaa", "aa") == [(0, 1 + 1), (1, 3)]


def test_crlf_document_keeps_offsets(tmp_path: Path) -> None:
    raw = b"Line one.\r\nBP 130/85 mmHg.\r\nLine three."
    path = tmp_path / "doc.txt"
    path.write_bytes(raw)
    doc = read_doc(path)
    assert "\r\n" in doc  # no newline translation
    start, end = locate(doc, "BP 130/85 mmHg.")[0]
    assert (start, end) == (11, 26)
    assert raw[start:end].decode() == "BP 130/85 mmHg."


def test_hashes() -> None:
    assert sha256_hex("abc") == hashlib.sha256(b"abc").hexdigest()
    assert sha8("abc") == sha256_hex("abc")[:8]
    doc = "xx BMI 41.2 yy"
    assert quote_sha256(doc, 3, 11) == sha256_hex("BMI 41.2")
    with pytest.raises(ValueError):
        quote_sha256(doc, 5, 3)
    with pytest.raises(ValueError):
        quote_sha256(doc, 0, 99)
