#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.models.Dashy import DashySection

@dataclass
class SidecarConfig:
    """Sidecar configuration."""
    sections: List[DashySection] = field(default_factory=list)

class Sidecar:
    logging = None

    def __init__(self, logging):
        self.logging = logging

    def load_config(self, path: str) -> SidecarConfig:
        """Load the existing Sidecar configuration file."""
        cfg = SidecarConfig()

        return cfg

    def get_section_icons(self) -> Dict[str, str]:
        """Get the section icons from the config."""

        # Section icon defaults
        SECTION_ICONS: Dict[str, str] = {
            "Media & Entertainment": "fas fa-photo-video",
            "Networking": "fas fa-network-wired",
            "Network Monitoring": "fas fa-tachometer-alt-fast",
            "System Monitoring": "fas fa-monitor-heart-rate",
            "Home Control": "fas fa-house-signal",
            "Productivity": "fas fa-bookmark",
        }

        return SECTION_ICONS