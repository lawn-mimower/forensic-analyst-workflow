"""The PDF fallback must fail loudly instead of inventing figures."""
import builtins
from pathlib import Path

import pytest

from pipeline import test_normalization as tn


def test_pdf_without_extractors_raises(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def no_tabula_or_camelot(name, *args, **kwargs):
        if name in ("tabula", "camelot"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tabula_or_camelot)
    pdf = tmp_path / "statement.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(RuntimeError, match="No PDF table extractor"):
        tn._extract_pdf_tables(Path(pdf))
