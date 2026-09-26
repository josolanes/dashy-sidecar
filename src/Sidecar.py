#!/usr/bin/env python3

import yaml
import os
import logging

from dataclasses import dataclass, field
from typing import Dict, List

from src.DynamicObject import DynamicObject


@dataclass
class SidecarConfig:
    """Sidecar configuration."""
    sections: List[DynamicObject] = field(default_factory=list)

class Sidecar:
    log = logging
    config_path = None

    def __init__(self, log):
        self.log = log

    def load_config(self, path: str) -> Dict[str, DynamicObject]:
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
                sec = DynamicObject()
                sec.name=rs.get("name", "")
                sec.icon=rs.get("icon", "fas fa-folder")
                sec.display_data=rs.get("displayData", {})
                cfg[sec.name] = sec
        else:
            cfg = self._default_sections()

        return cfg

    @staticmethod
    def _default_sections() -> Dict[str, DynamicObject]:
        default_icons: Dict[str, str] = {
            "Media & Entertainment": "fas fa-photo-video",
            "Networking": "fas fa-network-wired",
            "Network Monitoring": "fas fa-tachometer-alt-fast",
            "System Monitoring": "fas fa-monitor-heart-rate",
            "Home Control": "fas fa-house-signal",
            "Productivity": "fas fa-bookmark"
        }

        defaults: Dict[str, DynamicObject] = {}

        for name, icon in default_icons.items():
            tmp = DynamicObject()
            tmp.name = name
            tmp.icon = icon
            tmp.display_data = {
                "sortBy": "default",
                "cols": 2,
                "itemCountX": 6
            }

            defaults[name] = tmp

        return defaults
