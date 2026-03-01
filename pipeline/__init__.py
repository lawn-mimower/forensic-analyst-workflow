"""
Pipeline package for forensic accounting document processing.

Modules:
    table_extractor — Context-aware table extraction from PDF, DOCX, Excel, CSV.
    data_normalizer — Table classification, normalization, and DuckDB loading.
"""

try:
    from pipeline.table_extractor import TableExtractor, ExtractedTable
except ImportError:
    # table_extractor not yet created; use the compatibility shim
    TableExtractor = None  # type: ignore[assignment,misc]
    from pipeline.data_normalizer import ExtractedTable

from pipeline.data_normalizer import DataNormalizer, NormalizationResult

__all__ = [
    "TableExtractor",
    "ExtractedTable",
    "DataNormalizer",
    "NormalizationResult",
]
