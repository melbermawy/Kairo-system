"""
BrandBrain API endpoints.

PR-5: Compile kickoff + status endpoints.
PR-7: Full API surface.

Read-path vs Work-path boundary (spec Section 1.1):
- Read-path: GET /latest, GET /history, GET /status - DB reads only
- Work-path: POST /compile - schedules async work
"""
