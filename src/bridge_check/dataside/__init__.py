"""Data-side tools: drafting authored documents (route 1), proposing candidates (route 2),
the OpenAI wrapper, the frozen cue table and the sentence splitter.

Nothing in the pipeline (`cli`, `extract`, `verify`, `compute`, `rules`, `store`) may
import this package; `tests/test_import_boundary.py` enforces it. Data-side output never
enters gold without human verification (annotation guide P-02, P-03).
"""
