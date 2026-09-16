#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class DashySection:
    """A Dashy section."""
    name: str
    icon: str = ""
    display_data: Dict[str, Any] = field(default_factory=lambda: {
        "sortBy": "default",
        "cols": 2,
        "itemCountX": 6,
    })
    items: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class DashyConfig:
    """Full Dashy configuration."""
    pageInfo: Dict[str, Any] = field(default_factory=lambda: {"title": "", "description": ""})
    appConfig: Dict[str, Any] = field(default_factory=dict)
    sections: List[DashySection] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)