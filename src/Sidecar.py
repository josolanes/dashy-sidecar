#!/usr/bin/env python3

import yaml
import os
import logging

from dataclasses import dataclass, field
from typing import Dict, List

from src.Dashy import DashySection

@dataclass
class SidecarConfig:
    """Sidecar configuration."""
    sections: List[DashySection] = field(default_factory=list)

class Sidecar:
    log = logging
    config_path = None

    def __init__(self, log):
        self.log = log

    def load_config(self, path: str) -> Dict[str, DashySection]:
        """Load the existing Sidecar configuration file."""
        cfg = {}

        self.config_path = path

        if not os.path.exists(path):
            self.log.info("No existing sidecar config at %s – will use defaults", path)
            return self._default_sections()
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.log.error("Failed to read sidecar config: %s", e)
            return cfg

        if isinstance(data, dict):
            # Parse sections if present
            raw_sections = data.get("sections", []) or []
            for rs in raw_sections:
                sec = DashySection(
                    name=rs.get("name", ""),
                    icon=rs.get("icon", "fas fa-folder"),
                    order=rs.get("order", 999),
                    display_data=rs.get("displayData", {}),
                )
                cfg[sec.name] = sec
        else:
            cfg = self._default_sections()

        return cfg

    @staticmethod
    def _default_sections() -> Dict[str, DashySection]:
        return {
            "Media & Entertainment": DashySection(
                name="Media & Entertainment",
                icon="fas fa-photo-video",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                }),
            "Networking": DashySection(
                name="Networking",
                icon="fas fa-network-wired",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                }),
            "Network Monitoring": DashySection(
                name="Network Monitoring",
                icon="fas fa-tachometer-alt-fast",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                }),
            "System Monitoring": DashySection(
                name="System Monitoring",
                icon="fas fa-monitor-heart-rate",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                }),
            "Home Control": DashySection(
                name="Home Control",
                icon="fas fa-house-signal",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                }),
            "Productivity": DashySection(
                name="Productivity",
                icon="fas fa-bookmark",
                display_data={
                    "sortBy": "default",
                    "cols": 2,
                    "itemCountX": 6
                })
        }
