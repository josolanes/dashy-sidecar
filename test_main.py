#!/usr/bin/env python3
"""Unit tests for the Dashy Kubernetes sidecar."""

import os
import sys
import tempfile
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    K8sMeta, K8sItem, DashySection, DashyConfig,
    build_sections, sections_have_changed,
    marshal_config, load_config, write_config, get_section_icon,
    _extract_k8s_meta,
)


def test_extract_k8s_meta():
    labels = {
        "dashy.title": "My Service",
        "dashy.description": "A cool service",
        "dashy.url": "https://example.com",
        "dashy.icon": "hl-myicon",
        "dashy.section": "Networking",
    }
    meta = _extract_k8s_meta(labels)
    assert meta.title == "My Service"
    assert meta.description == "A cool service"
    assert meta.url == "https://example.com"
    assert meta.icon == "hl-myicon"
    assert meta.section == "Networking"
    assert _extract_k8s_meta(None) == K8sMeta()
    assert _extract_k8s_meta({}) == K8sMeta()


def test_build_sections():
    items = [
        K8sItem(name="svc1", namespace="default", kind="Service",
                meta=K8sMeta(title="Jellyfin", section="Media & Entertainment",
                             icon="hl-jellyfin", url="https://jellyfin.local")),
        K8sItem(name="svc2", namespace="default", kind="Service",
                meta=K8sMeta(title="Plex", section="Media & Entertainment",
                             icon="hl-plex")),
        K8sItem(name="svc3", namespace="default", kind="Service",
                meta=K8sMeta(title="Pi-Hole", section="Networking",
                             description="DNS ad-blocking", icon="hl-pihole")),
        K8sItem(name="svc4", namespace="default", kind="Service",
                meta=K8sMeta(title="Unlabelled", section="", icon="hl-something")),
    ]
    sections = build_sections(items)
    assert len(sections) == 3
    assert sections[0].name == "Media & Entertainment
    assert sections[1].name == "Networking"
    assert sections[2].name == "Unnamed"
    assert len(sections[0].items) == 2
    assert sections[0].items[0]["title"] == "Jellyfin"
    assert sections[0].items[1]["title"] == "Plex"
    assert len(sections[1].items) == 1
    assert sections[1].items[0]["title"] == "Pi-Hole"
    assert sections[1].items[0]["description"] == "DNS ad-blocking"
    assert len(sections[2].items) == 1
    assert sections[2].items[0]["title"] == "Unlabelled"


def test_build_sections_empty():
    assert build_sections([]) == []


def test_build_sections_missing_section():
    items = [
        K8sItem(name="svc1", namespace="default", kind="Service",
                meta=K8sMeta(title="Only Title", section="Test")),
        K8sItem(name="svc2", namespace="default", kind="Service",
                meta=K8sMeta(url="https://example.com", icon="hl-icon")),
    ]
    sections = build_sections(items)
    assert len(sections) == 2
    smap = {s.name: s for s in sections}
    assert "Test" in smap
    assert "Unnamed" in smap
    assert len(smap["Test"].items) == 1
    assert smap["Test"].items[0]["title"] == "Only Title"
    ui = smap["Unnamed"].items
    assert len(ui) == 1
    assert "title" not in ui[0]
    assert ui[0].get("url") == "https://example.com"
    assert ui[0].get("icon") == "hl-icon"


def test_marshal_config():
    cfg = DashyConfig(
        pageInfo={
            "title": "Demo Homelab",
            "description": "Live Demo of Dashy",
            "navLinks": [
                {"title": "GitHub", "path": "https://github.com/Lissy93/dashy"},
                {"title": "Documentation", "path": "https://dashy.to/docs"},
            ],
        },
        appConfig={
            "theme": "nord-frost",
            "customColors": {
                "material-dark-original": {
                    "primary": "#f36558",
                    "background": "#39434C",
                },
            },
            "enableErrorReporting": True,
            "layout": "auto",
            "iconSize": "medium",
        },
        sections=[
            DashySection(
                name="Media & Entertainment",
                icon="fas fa-photo-video",
                display_data={"sortBy": "default", "cols": 2, "itemCountX": 6},
                items=[
                    {"title": "Jellyfin", "icon": "hl-jellyfin", "url": "https://jellyfin.local"},
                    {"title": "Plex", "icon": "hl-plex"},
                ],
            ),
            DashySection(
                name="Networking",
                icon="fas fa-network-wired",
                display_data={"sortBy": "default", "cols": 2, "itemCountX": 6},
                items=[
                    {"title": "Pi-Hole", "description": "DNS ad-blocking", "icon": "hl-pihole"},
                ],
            ),
        ],
    )
    yaml_str = marshal_config(cfg)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["pageInfo"]["title"] == "Demo Homelab"
    assert parsed["pageInfo"]["description"] == "Live Demo of Dashy"
    assert len(parsed["pageInfo"]["navLinks"]) == 2
    assert parsed["appConfig"]["theme"] == "nord-frost"
    assert parsed["appConfig"]["enableErrorReporting"] is True
    assert parsed["appConfig"]["layout"] == "auto"
    assert parsed["appConfig"]["iconSize"] == "medium"
    secs = parsed["sections"]
    assert len(secs) == 2
    assert secs[0]["name"] == "Media & Entertainment"
    assert secs[0]["icon"] == "fas fa-photo-video"
    assert len(secs[0]["items"]) == 2
    assert secs[0]["items"][0]["title"] == "Jellyfin"
    assert secs[1]["name"] == "Networking"
    assert secs[1]["items"][0]["description"] == "DNS ad-blocking"
    assert secs[0]["filteredItems"]
    assert secs[1]["filteredItems"]


def test_preserve_appConfig():
    yaml_content = """pageInfo:
  title: "Test"
  description: "Test config"
appConfig:
  theme: nord-frost
  customColors:
    material-dark-original:
      primary: '#f36558'
      background: '#39434C'
  enableErrorReporting: true
  layout: auto
  iconSize: medium
sections:
  - name: Old Section
    icon: fas fa-folder
    displayData:
      sortBy: default
      cols: 2
      itemCountX: 6
    items:
      - title: Old Item
        icon: hl-old
    filteredItems:
      - title: Old Item
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(yaml_content)
        config_path = f.name
    try:
        cfg = load_config(config_path)
        assert cfg.pageInfo["title"] == "Test"
        assert cfg.appConfig["theme"] == "nord-frost"
        cfg.sections = build_sections([
            K8sItem(name="new-svc", namespace="default", kind="Service",
                    meta=K8sMeta(title="New Service", section="New Section",
                                 icon="hl-new")),
        ])
        write_config(config_path, marshal_config(cfg))
        cfg2 = load_config(config_path)
        assert cfg2.pageInfo["title"] == "Test"
        assert cfg2.appConfig["theme"] == "nord-frost"
        assert len(cfg2.sections) == 1
        assert cfg2.sections[0].name == "New Section"
    finally:
        os.unlink(config_path)


def test_sections_have_changed():
    s1 = [DashySection(name="A", items=[{"title": "X"}])]
    s2 = [DashySection(name="A", items=[{"title": "X"}])]
    assert not sections_have_changed(s1, s2)
    s3 = [DashySection(name="A", items=[{"title": "Y"}])]
    assert sections_have_changed(s1, s3)
    s4 = [DashySection(name="A", items=[{"title": "X"}]),
          DashySection(name="B", items=[{"title": "Y"}])]
    assert sections_have_changed(s1, s4)


def test_get_section_icon():
    assert get_section_icon("Media & Entertainment") == "fas fa-photo-video"
    assert get_section_icon("Networking") == "fas fa-network-wired"
    assert get_section_icon("Custom Section") == "fas fa-folder"


def test_write_config_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        config_path = f.name
    try:
        cfg = DashyConfig(
            pageInfo={"title": "Test", "description": "Test"},
            appConfig={"theme": "test"},
            sections=[DashySection(name="Section1", icon="fas fa-test",
                                  items=[{"title": "Item1"}])],
        )
        write_config(config_path, marshal_config(cfg))
        with open(config_path) as f:
            content = f.read()
        assert "pageInfo:" in content
        assert "appConfig:" in content
        assert "sections:" in content
        assert "name: 'Section1'" in content
        assert "title: 'Item1'" in content
    finally:
        os.unlink(config_path)


def test_integration_full_workflow():
    yaml_content = """pageInfo:
  title: "Demo Homelab"
  description: "Live Demo of Dashy"
  navLinks:
    - title: GitHub
      path: https://github.com/Lissy93/dashy
appConfig:
  theme: nord-frost
  customColors:
    material-dark-original:
      primary: '#f36558'
      background: '#39434C'
  enableErrorReporting: true
  layout: auto
  iconSize: medium
sections: []
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(yaml_content)
        config_path = f.name
    try:
        items = [
            K8sItem(name="jellyfin", namespace="default", kind="Service",
                    meta=K8sMeta(title="Jellyfin", section="Media & Entertainment",
                                 icon="hl-jellyfin", url="https://jellyfin.local",
                                 description="Media server")),
            K8sItem(name="plex", namespace="default", kind="Service",
                    meta=K8sMeta(title="Plex", section="Media & Entertainment",
                                 icon="hl-plex")),
            K8sItem(name="pihole", namespace="default", kind="Service",
                    meta=K8sMeta(title="Pi-Hole", section="Networking",
                                 description="DNS ad-blocking", icon="hl-pihole")),
            K8sItem(name="opnsense", namespace="default", kind="Service",
                    meta=K8sMeta(title="OPNSense", section="Networking",
                                 description="Firewall and network config",
                                 icon="hl-opnsense")),
        ]
        cfg = load_config(config_path)
        new_sections = build_sections(items)
        assert sections_have_changed(cfg.sections, new_sections)
        cfg.sections = new_sections
        write_config(config_path, marshal_config(cfg))
        cfg2 = load_config(config_path)
        parsed = yaml.safe_load(open(config_path))
        assert cfg2.pageInfo["title"] == "Demo Homelab"
        assert parsed["appConfig"]["theme"] == "nord-frost"
        assert parsed["appConfig"]["enableErrorReporting"] is True
        assert len(parsed["sections"]) == 2
        assert parsed["sections"][0]["name"] == "Media & Entertainment"
        assert len(parsed["sections"][0]["items"]) == 2
        assert parsed["sections"][0]["items"][0]["title"] == "Jellyfin"
        assert parsed["sections"][0]["items"][0]["description"] == "Media server"
        assert parsed["sections"][1]["name"] == "Networking"
        assert len(parsed["sections"][1]["items"]) == 2
        print("\nAll tests passed!")
    finally:
        os.unlink(config_path)


if __name__ == "__main__":
    test_extract_k8s_meta()
    test_build_sections()
    test_build_sections_empty()
    test_build_sections_missing_section()
    test_marshal_config()
    test_preserve_appConfig()
    test_sections_have_changed()
    test_get_section_icon()
    test_write_config_file()
    test_integration_full_workflow()

