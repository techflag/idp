"""Community application asset service boundary.

COMMUNITY_APPLICATION_ASSETS_STUB

The public GitHub snapshot must not contain the complete long-document
application-run planner. Community users can use single-page sample extraction
and basic Skill debugging; commercial deployments provide the full private
application runner through internal extensions.
"""

from __future__ import annotations

from typing import Any


class ApplicationAssetService:
    def __init__(self, **_: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(
            f"{name} is not available in the GitHub community application asset boundary. "
            "Full application runs and long-document orchestration are commercial private extensions."
        )
