"""Modular extraction runtime kernel.

The package keeps the generic extraction runtime separate from route and
application orchestration code.  Community-core modules live here; commercial
extensions should plug in through providers instead of adding business-specific
branches to the runtime.
"""

from app.services.extraction_runtime.kernel import ExtractionRuntimeKernel
from app.services.extraction_runtime.application_run import build_application_extraction_schema_definition
from app.services.extraction_runtime.models import (
    ExtractionRuntimePorts,
    ExtractionRuntimePrepared,
    ExtractionRuntimeRequest,
    ExtractionRuntimeResult,
)
from app.services.extraction_runtime.skill_test import build_skill_test_runtime_request

__all__ = [
    "ExtractionRuntimeKernel",
    "ExtractionRuntimePorts",
    "ExtractionRuntimePrepared",
    "ExtractionRuntimeRequest",
    "ExtractionRuntimeResult",
    "build_application_extraction_schema_definition",
    "build_skill_test_runtime_request",
]
