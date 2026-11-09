"""Data-side tools: drafting authored documents (route 1), proposing candidates (route 2),
and the OpenAI wrapper. The frozen cue table (`bridge_check.cues`) and the sentence
splitter (`bridge_check.sentences`) are shared with the pipeline and live outside this package.

Nothing in the pipeline (`cli`, `extract`, `verify`, `compute`, `rules`, `store`) may
import this package; `tests/test_import_boundary.py` enforces it. Data-side output never
enters gold without human verification (annotation guide P-02, P-03).
"""
