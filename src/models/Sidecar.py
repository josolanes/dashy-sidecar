#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class SidecarSection:
    """A Sidecar section."""
    name: str
    icon: str = ""
    display_data: Dict[str, Any] = field(default_factory=lambda: {
        "sortBy": "default",
        "cols": 2,
        "itemCountX": 6,
    })


@dataclass
class SidecarConfig:
    """Sidecar configuration."""
    sections: List[SidecarSection] = field(default_factory=list)