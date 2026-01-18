"""
Kairo Hero Tasks.

PR1: Background execution infrastructure for opportunities v2.
"""

from .generate import execute_opportunities_job, JobResult

__all__ = [
    "execute_opportunities_job",
    "JobResult",
]
