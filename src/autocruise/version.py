from __future__ import annotations


APP_NAME = "AutoCruiseCE"
APP_TITLE = "AutoCruise CE"
APP_VERSION = "1.1.0"
COMPANY_NAME = "Sharaku Satoh"
PRODUCT_NAME = "AutoCruise CE"
COPYRIGHT = "Copyright (c) 2026 Sharaku Satoh"


def version_tuple() -> tuple[int, int, int, int]:
    parts = [int(part) for part in APP_VERSION.split(".")[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])
