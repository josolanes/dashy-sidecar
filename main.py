#!/usr/bin/env python3
"""
Kubernetes sidecar for Dashy.

Monitors Kubernetes Services, Ingresses, and IngressRoutes (Gateway API) for
the following labels and updates a Dashy conf.yml file with appropriate
sections and items.

Usage:
    python3 main.py [--conf /app/config/conf.yml] [--interval 60] [--kubeconfig ~/.kube/config]

Environment variables:
    DASHY_CONF   - path to conf.yml (default: /app/config/conf.yml)
    SYNC_INTERVAL - sync interval in seconds (default: 60)
    KUBECONFIG   - path to kubeconfig (default: in-cluster)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import threading
import yaml
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# K8s client (optional – graceful degradation)
# ---------------------------------------------------------------------------

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    HAS_K8S = True
except ImportError:
    HAS_K8S = False

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class K8sMeta:
    """Parsed dashy metadata from a Kubernetes resource."""
    title: str = ""
    description: str = ""
    url: str = ""
    icon: str = ""
    section: str = ""


@dataclass
class K8sItem:
    """A single Kubernetes resource with dashy labels."""
    name: str
    namespace: str
    kind: str
    meta: K8sMeta = field(default_factory=K8sMeta)


@dataclass
class DashySection:
    """A Dashy section."""
    name: str
    icon: str = ""
    description: str = ""
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


# Section icon defaults
SECTION_ICONS: Dict[str, str] = {
    "Media & Entertainment": "fas fa-photo-video",
    "Networking": "fas fa-network-wired",
    "Network Monitoring": "fas fa-tachometer-alt-fast",
    "System Monitoring": "fas fa-monitor-heart-rate",
    "Home Control": "fas fa-house-signal",
    "Productivity": "fas fa-bookmark",
}


def get_section_icon(name: str) -> str:
    return SECTION_ICONS.get(name, "fas fa-folder")


# ---------------------------------------------------------------------------
# Kubernetes collectors
# ---------------------------------------------------------------------------

def _extract_k8s_meta(labels: Optional[Dict[str, str]]) -> K8sMeta:
    """Extract dashy labels from a Kubernetes resource's labels dict."""
    if not labels:
        return K8sMeta()

    m = K8sMeta(
        title=labels.get("dashy.title", ""),
        description=labels.get("dashy.description", ""),
        url=labels.get("dashy.url", ""),
        icon=labels.get("dashy.icon", ""),
        section=labels.get("dashy.section", ""),
    )
    return m


def collect_services() -> List[K8sItem]:
    """Collect all Services with dashy labels."""
    if not HAS_K8S:
        return []

    try:
        core = client.CoreV1Api()
        items: List[K8sItem] = []
        for svc in core.list_service_for_all_namespaces().items:
            meta = _extract_k8s_meta(svc.metadata.labels)
            if meta.title or meta.description or meta.url or meta.icon:
                items.append(K8sItem(
                    name=svc.metadata.name,
                    namespace=svc.metadata.namespace,
                    kind="Service",
                    meta=meta,
                ))
        return items
    except Exception as e:
        logging.warning("Failed to list Services: %s", e)
        return []


def collect_ingresses() -> List[K8sItem]:
    """Collect all Ingresses with dashy labels."""
    if not HAS_K8S:
        return []

    try:
        net = client.NetworkingV1Api()
        items: List[K8sItem] = []
        for ing in net.list_ingress_for_all_namespaces().items:
            meta = _extract_k8s_meta(ing.metadata.labels)
            if meta.title or meta.description or meta.url or meta.icon:
                items.append(K8sItem(
                    name=ing.metadata.name,
                    namespace=ing.metadata.namespace,
                    kind="Ingress",
                    meta=meta,
                ))
        return items
    except Exception as e:
        logging.warning("Failed to list Ingresses: %s", e)
        return []


def collect_ingress_routes() -> List[K8sItem]:
    """
    Collect IngressRoute custom resources (Gateway API / Kong CRD).

    Uses the discovery API to locate IngressRoute and then queries each
    namespace for those resources via the dynamic client.
    """
    if not HAS_K8S:
        return []

    try:
        discovery = client.DiscoveryApi()
        groups = discovery.get_api_groups()

        # Check if IngressRoute group is available
        has_route = False
        for group in groups.groups:
            for ver in group.versions:
                if "gateway.networking.k8s.io" in ver.group_version or \
                   "ingressroute" in ver.group_version.lower():
                    has_route = True
                    break

        if not has_route:
            return []

        # Collect namespaces
        ns_client = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in ns_client.list_namespace().items]

        items: List[K8sItem] = []
        api_version = "gateway.networking.k8s.io/v1"
        plural = "ingressroutes"

        for ns in namespaces:
            try:
                path = f"/apis/{api_version}/namespaces/{ns}/{plural}"
                resp = client.ApiClient().request("GET", path)
                body = json.loads(resp.data)
                for ir in body.get("items", []):
                    meta_obj = ir.get("metadata", {})
                    raw_labels = meta_obj.get("labels", {})
                    meta = _extract_k8s_meta(raw_labels)

                    title = meta.title or meta_obj.get("name", "")

                    items.append(K8sItem(
                        name=meta_obj.get("name", ""),
                        namespace=ns,
                        kind="IngressRoute",
                        meta=K8sMeta(
                            title=title,
                            description=meta.description,
                            url=meta.url,
                            icon=meta.icon,
                            section=meta.section,
                        ),
                    ))
            except Exception:
                continue

        return items
    except Exception as e:
        logging.warning("Failed to list IngressRoutes: %s", e)
        return []


def collect_all() -> List[K8sItem]:
    """Collect items from all supported Kubernetes resource types."""
    all_items: List[K8sItem] = []

    for fn in [collect_services, collect_ingresses, collect_ingress_routes]:
        try:
            items = fn()
            logging.info(f"  {fn.__name__}: {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            logging.warning(f"  {fn.__name__}: {e}")

    return all_items


# ---------------------------------------------------------------------------
# Config loading & building
# ---------------------------------------------------------------------------

def load_config(path: str) -> DashyConfig:
    """Load the existing Dashy configuration file."""
    cfg = DashyConfig()

    if not os.path.exists(path):
        logging.info("No existing config at %s – will create fresh", path)
        return cfg
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logging.error("Failed to read config: %s", e)
        return cfg

    if isinstance(data, dict):
        cfg.raw = data
        cfg.pageInfo = data.get("pageInfo", {}) or {}
        cfg.appConfig = data.get("appConfig", {}) or {}
        # Parse sections if present
        raw_sections = data.get("sections", []) or []
        for rs in raw_sections:
            if isinstance(rs, dict):
                sec = DashySection(
                    name=rs.get("name", ""),
                    icon=rs.get("icon", ""),
                    description=rs.get("description", ""),
                    display_data=rs.get("displayData", {
                        "sortBy": "default",
                        "cols": 2,
                        "itemCountX": 6,
                    }) or {},
                )
                raw_items = rs.get("items", []) or []
                for ri in raw_items:
                    if isinstance(ri, dict):
                        sec.items.append(ri)
                cfg.sections.append(sec)
    else:
        logging.warning("Config is not a YAML mapping – using defaults")

    return cfg


def build_sections(items: List[K8sItem]) -> List[DashySection]:
    """Group collected items into Dashy sections."""
    groups: Dict[str, List[K8sItem]] = {}
    for item in items:
        section_name = item.meta.section or "Unnamed"
        groups.setdefault(section_name, []).append(item)

    section_names = sorted(groups.keys())
    sections: List[DashySection] = []

    for name in section_names:
        section_items = groups[name]
        section_items.sort(key=lambda i: i.name)

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

        sections.append(DashySection(
            name=name,
            icon=get_section_icon(name),
            items=dashy_items,
        ))

    return sections


def sections_have_changed(old: List[DashySection], new: List[DashySection]) -> bool:
    """Check if the sections content has changed (ignoring displayData)."""
    if len(old) != len(new):
        return True

    for os_, ns_ in zip(old, new):
        if os_.name != ns_.name:
            return True
        if os_.items != ns_.items:
            return True

    return False


# ---------------------------------------------------------------------------
# YAML writing (manual to preserve exact Dashy format)
# ---------------------------------------------------------------------------

def _escape(s: str) -> str:
    """Quote a string for YAML output."""
    return "'" + s.replace("'", "''") + "'"


def marshal_config(cfg: DashyConfig) -> str:
    """Manually marshal the config to match Dashy's expected YAML format."""
    lines: List[str] = []

    # pageInfo
    lines.append("pageInfo:")
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
            if sec.description:
                lines.append(f"    description: {_escape(sec.description)}")

            # displayData
            dd = sec.display_data
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


def write_config(path: str, config_str: str) -> None:
    """Atomically write the config file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(config_str)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(conf_path: str, interval: int) -> None:
    """Main sync loop."""
    logging.info("Starting Dashy sidecar")
    logging.info("  Config path : %s", conf_path)
    logging.info("  Sync interval: %ds", interval)

    if not HAS_K8S:
        logging.error("kubernetes Python library not installed – cannot sync")
        sys.exit(1)

    # Try to load in-cluster or kubeconfig
    try:
        config.load_incluster_config()
        logging.info("Using in-cluster config")
    except config.ConfigException:
        try:
            kubeconf = os.environ.get("KUBECONFIG", "")
            if kubeconf:
                config.load_kube_config(kubeconf)
                logging.info(f"Using kubeconfig: {kubeconf}")
            else:
                config.load_kube_config()
                logging.info("Using default kubeconfig")
        except config.ConfigException as e:
            logging.error("Cannot load Kubernetes config: %s", e)
            sys.exit(1)

    # Initial sync
    sync(conf_path)

    # Periodic sync
    timer = threading.Timer(interval, run_loop, [conf_path, interval])
    timer.daemon = True
    timer.start()

    # Block on SIGTERM
    signal.pause()


def sync(conf_path: str) -> None:
    """Perform a single sync cycle."""
    logging.info("─── Syncing Dashy config ───")

    # Collect
    items = collect_all()
    if not items:
        logging.info("No dashy labels found – keeping existing config")
        return

    # Build sections
    new_sections = build_sections(items)
    logging.info("Built %d sections with %d total items", len(new_sections), len(items))

    # Load existing config
    cfg = load_config(conf_path)

    # Check for changes
    old_sections = cfg.sections
    if not sections_have_changed(old_sections, new_sections):
        logging.info("No changes – skipping write")
        return

    # Update config
    cfg.sections = new_sections

    # Write
    try:
        config_str = marshal_config(cfg)
        write_config(conf_path, config_str)
        logging.info("Config written successfully")
    except Exception as e:
        logging.error("Failed to write config: %s", e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Kubernetes sidecar for Dashy")
    parser.add_argument("--conf", default=os.environ.get("DASHY_CONF", "/app/config/conf.yml"),
                        help="Path to Dashy conf.yml")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("SYNC_INTERVAL", "60")),
                        help="Sync interval in seconds (default: 60)")
    parser.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", ""),
                        help="Path to kubeconfig file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.kubeconfig:
        os.environ["KUBECONFIG"] = args.kubeconfig

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )

    run_loop(args.conf, args.interval)


if __name__ == "__main__":
    main()

