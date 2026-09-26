#!/usr/bin/env python3

import yaml
import os

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.K8s import K8sItem
from src.DynamicObject import DynamicObject

@dataclass
class DashyConfig:
    """Full Dashy configuration."""
    pageInfo: Dict[str, Any] = field(default_factory=lambda: {"title": "", "description": ""})
    appConfig: Dict[str, Any] = field(default_factory=dict)
    sections: List[DynamicObject] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

class Dashy:
    logging = None

    def __init__(self, logging):
        self.logging = logging

    def load_config(self, path: str) -> DashyConfig:
        """Load the existing Dashy configuration file."""
        cfg = DashyConfig()

        if not os.path.exists(path):
            self.logging.info("No existing config at %s – will create fresh", path)
            return cfg
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self.logging.error("Failed to read config: %s", e)
            return cfg

        if isinstance(data, dict):
            cfg.raw = data
            cfg.pageInfo = data.get("pageInfo", {}) or {}
            cfg.appConfig = data.get("appConfig", {}) or {}
            # Parse sections if present
            raw_sections = data.get("sections", []) or []
            for rs in raw_sections:
                if isinstance(rs, dict):
                    sec = DynamicObject()
                    sec.name = rs.get("name", "")
                    sec.icon = rs.get("icon", "")
                    sec.display_data = rs.get("displayData", {}) or {}
                    raw_items = rs.get("items", []) or []
                    for ri in raw_items:
                        if isinstance(ri, dict):
                            if sec.items is None:
                                sec.items = []
                            sec.items.append(ri)
                    cfg.sections.append(sec)
        else:
            self.logging.warning("Config is not a YAML mapping – using defaults")

        return cfg

    def build_sections(self, items: List[K8sItem], sidecar_sections: Dict[str, DynamicObject]) -> List[DynamicObject]:
        """Group collected items into Dashy sections."""
        groups: Dict[str, List[K8sItem]] = {}
        for item in items:
            section_name = item.meta.section or "Unnamed"
            groups.setdefault(section_name, []).append(item)

        groups_keys = list(sorted(groups.keys()))
        sidecar_sections_keys = list(sidecar_sections.keys())

        section_names = list(dict.fromkeys(sidecar_sections_keys + groups_keys))

        sections: List[DynamicObject] = []

        for name in section_names:
            if name not in groups:
                continue

            section_items = groups[name]
            section_items.sort(key=lambda i: i.meta.title)

            dashy_items: List[Dict[str, str]] = []
            for it in section_items:
                d: Dict[str, str] = {}
                if it.meta.title:
                    d["title"] = it.meta.title
                if it.meta.description:
                    d["description"] = it.meta.description
                if it.meta.url:
                    d["url"] = it.meta.url
                if it.meta.icon:
                    d["icon"] = it.meta.icon
                dashy_items.append(d)

            section = DynamicObject()
            section.name = name
            section.icon = sidecar_sections[name].icon if name in sidecar_sections else "fas fa-folder"
            section.display_data = sidecar_sections[name].display_data if name in sidecar_sections else {
                "sortBy": "default",
                "cols": 2,
                "itemCountX": 6,
            }
            section.items = dashy_items

            sections.append(section)

        return sections

    def sections_have_changed(self, old: List[DynamicObject], new: List[DynamicObject]) -> bool:
        """Check if the section content has changed (ignoring displayData)."""
        if len(old) != len(new):
            return True

        for os_, ns_ in zip(old, new):
            keys = list(dict.fromkeys(list(os_.keys()) + list(ns_.keys())))

            for key in keys:
                if key not in os_.__dict__ or key not in ns_.__dict__:
                    return True

                if os_.__dict__[key] != ns_.__dict__[key]:
                    return True

        return False

    def marshal_config(self, cfg: DashyConfig) -> str:
        """Manually marshal the config to match Dashy's expected YAML format."""
        lines: List[str] = ["pageInfo:"]

        # pageInfo
        title = cfg.pageInfo.get("title", "")
        desc = cfg.pageInfo.get("description", "")
        if title:
            lines.append(f"  title: {_escape(title)}")
        if desc:
            lines.append(f"  description: {_escape(desc)}")

        nav_links = cfg.pageInfo.get("navLinks", [])
        if nav_links:
            lines.append("  navLinks:")
            for nl in nav_links:
                if isinstance(nl, dict):
                    lines.append(f"    - title: {_escape(nl.get('title', ''))}")
                    lines.append(f"      path: {_escape(nl.get('path', ''))}")
                elif isinstance(nl, str):
                    lines.append(f"    - title: {_escape(nl)}")
                    lines.append(f"      path: ''")

        # appConfig
        lines.append("appConfig:")
        ac = cfg.appConfig
        if ac.get("theme"):
            lines.append(f"  theme: {_escape(ac['theme'])}")
        if ac.get("customColors"):
            cc = ac["customColors"]
            if isinstance(cc, dict):
                lines.append("  customColors:")
                for theme_name, theme_data in cc.items():
                    lines.append(f"    {_escape(theme_name)}:")
                    if isinstance(theme_data, dict):
                        for k, v in theme_data.items():
                            lines.append(f"      {_escape(k)}: '{v}'")
        if ac.get("enableErrorReporting"):
            lines.append("  enableErrorReporting: true")
        if ac.get("layout"):
            lines.append(f"  layout: {_escape(ac['layout'])}")
        if ac.get("iconSize"):
            lines.append(f"  iconSize: {_escape(ac['iconSize'])}")

        # sections
        if not cfg.sections:
            lines.append("sections: []")
        else:
            lines.append("sections:")
            for si, sec in enumerate(cfg.sections):
                lines.append(f"  - name: {_escape(sec.name)}")
                if sec.icon:
                    lines.append(f"    icon: {_escape(sec.icon)}")

                # displayData
                dd = sec.display_data
                if dd is not None:
                    lines.append("    displayData:")
                    lines.append(f"      sortBy: {_escape(dd.get('sortBy', 'default'))}")
                    lines.append(f"      cols: {dd.get('cols', 2)}")
                    lines.append(f"      itemCountX: {dd.get('itemCountX', 6)}")
                    if dd.get("collapsed"):
                        lines.append("      collapsed: true")

                # items
                lines.append("    items:")
                for ii, item in enumerate(sec.items):
                    ref = f"ref_{si * 1000 + ii}"
                    lines.append(f"      - &{ref}")
                    if item.get("title"):
                        lines.append(f"        title: {_escape(item['title'])}")
                    if item.get("description"):
                        lines.append(f"        description: {_escape(item['description'])}")
                    if item.get("icon"):
                        lines.append(f"        icon: {_escape(item['icon'])}")
                    if item.get("url"):
                        lines.append(f"        url: {_escape(item['url'])}")

                # filteredItems
                lines.append("    filteredItems:")
                for ii in range(len(sec.items)):
                    ref = f"ref_{si * 1000 + ii}"
                    lines.append(f"      - *{ref}")

                lines.append("")

        return "\n".join(lines) + "\n"

    def write_config(self, path: str, config_str: str) -> None:
        """Atomically write the config file."""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(config_str)
        os.replace(tmp, path)

    def sync(self, conf_path: str, items: List[K8sItem], sidecar_sections: Dict[str, DynamicObject]) -> None:
        """Perform a single sync cycle."""
        self.logging.info("─── Syncing Dashy config ───")

        # Collect
        if not items:
            self.logging.info("No dashy annotations found – keeping existing config")
            return

        # Build sections
        new_sections = self.build_sections(items, sidecar_sections)
        self.logging.info("Built %d sections with %d total items", len(new_sections), len(items))

        # Load existing config
        cfg = self.load_config(conf_path)

        # Check for changes
        old_sections = cfg.sections
        if not self.sections_have_changed(old_sections, new_sections):
            self.logging.info("No changes – skipping write")
            return

        # Update config
        cfg.sections = new_sections

        # Write
        try:
            config_str = self.marshal_config(cfg)
            self.write_config(conf_path, config_str)
            self.logging.info("Config written successfully")
        except Exception as e:
            self.logging.error("Failed to write config: %s", e)

def _escape(s: str) -> str:
    """Quote a string for YAML output."""
    return "'" + s.replace("'", "''") + "'"