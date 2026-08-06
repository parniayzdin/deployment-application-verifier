"""Environment backed settings used by AWS Lambda handlers."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Required deployed resource names and report retention."""

    plans_table: str
    reports_table: str
    report_ttl_days: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        """Load required settings and fail with an actionable message."""

        plans_table = os.getenv("PLANS_TABLE", "")
        reports_table = os.getenv("REPORTS_TABLE", "")
        if not plans_table or not reports_table:
            raise RuntimeError("PLANS_TABLE and REPORTS_TABLE must be configured")
        ttl = int(os.getenv("REPORT_TTL_DAYS", "30"))
        if ttl < 1:
            raise RuntimeError("REPORT_TTL_DAYS must be positive")
        return cls(plans_table, reports_table, ttl)
