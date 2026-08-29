#!/usr/bin/env python3
"""
Kubernetes sidecar for Dashy.

Monitors Kubernetes Services, Ingresses, and IngressRoutes (Gateway API) for
the following annotations and updates a Dashy conf.yml file with appropriate
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
    """A single Kubernetes resource with dashy annotations."""
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

def _extract_k8s_meta(annotations: Optional[Dict[str, str]]) -> K8sMeta:
    """Extract dashy metadata from a Kubernetes resource's annotations dict."""
    if not annotations:
        return K8sMeta()

    return K8sMeta(
        title=annotations.get("dashy.title", ""),
        description=annotations.get("dashy.description", ""),
        url=annotations.get("dashy.url", ""),
        icon=annotations.get("dashy.icon", ""),
        section=annotations.get("dashy.section", ""),
    )


def collect_services() -> List[K8sItem]:
    """Collect all Services with dashy annotations."""
    if not HAS_K8S:
        return []

    try:
        core = client.CoreV1Api()
        items: List[K8sItem] = []
        for svc in core.list_service_for_all_namespaces().items:
            meta = _extract_k8s_meta(svc.metadata.annotations)
            name = svc.metadata.annotations.get("dashy.name")
            if not name:
                continue
            if meta.title or meta.description or meta.url or meta.icon:
                items.append(K8sItem(
                    name=name,
                    namespace=svc.metadata.namespace,
                    kind="Service",
                    meta=meta,
                ))
        return items
    except Exception as e:
        logging.warning("Failed to list Services: %s", e)
        return []


def collect_ingresses() -> List[K8sItem]:
    """Collect all Ingresses with dashy annotations."""
    if not HAS_K8S:
        return []

    try:
        net = client.NetworkingV1Api()
        items: List[K8sItem] = []
        for ing in net.list_ingress_for_all_namespaces().items:
            meta = _extract_k8s_meta(ing.metadata.annotations)
            name = ing.metadata.annotations.get("dashy.name")
            if not name:
                continue
            if meta.title or meta.description or meta.url or meta.icon:
                items.append(K8sItem(
                    name=name,
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

    Uses the dynamic client to query IngressRoute resources from all
    namespaces. Supports both gateway.networking.k8s.io IngressRoute and
    any other custom resources whose kind is "IngressRoute".
    """
    if not HAS_K8S:
        return []

    try:
        from kubernetes import dynamic
    except ImportError:
        logging.warning("kubernetes.dynamic not available – skipping IngressRoute collection")
        return []

    try:
        api = client.ApiClient()
        dynamic_client = dynamic.DynamicClient(api)

        # Use the discoverer to find all IngressRoute resources
        # The discoverer's search method looks up resources by kind
        discovered = dynamic_client.resources.search(kind="IngressRoute")

        if not discovered:
            return []

        # 'discovered' is a list of DynamicResource objects
        # Pick the first one (or use any matching one)
        ingress_route_resource = discovered[0]

        # Collect namespaces
        ns_client = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in ns_client.list_namespace().items]

        items: List[K8sItem] = []

        for ns in namespaces:
            try:
                resp = ingress_route_resource.get(namespace=ns)
                for ir in resp.get("items", []):
                    meta_obj = ir.get("metadata", {})
                    raw_annotations = meta_obj.get("annotations", {})
                    meta = _extract_k8s_meta(raw_annotations)

                    # If no dashy.url, try to derive from IngressRoute spec
                    url = meta.url
                    if not url:
                        url = _extract_ingress_route_url(ir)

                    name = raw_annotations.get("dashy.name")
                    if not name:
                        continue

                    title = meta.title or name

                    items.append(K8sItem(
                        name=name,
                        namespace=ns,
                        kind="IngressRoute",
                        meta=K8sMeta(
                            title=title,
                            description=meta.description,
                            url=url,
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


def _extract_ingress_route_url(ir: Dict[str, Any]) -> str:
    """
    Try to extract a URL from an IngressRoute resource's spec.

    Supports multiple common IngressRoute CRD formats:
    - Gateway API: spec.http.routes.action(s).target(s)
    - Kong: spec.http.routes[*].upstream(s) or spec.http.ups[*]
    - Generic: Any top-level 'url' or 'host' field in spec
    """
    spec = ir.get("spec", {}) or {}

    # Try common patterns
    # Pattern 1: spec.url or spec.host
    if spec.get("url"):
        return spec["url"]
    if spec.get("host"):
        return spec["host"]

    # Pattern 2: spec.http (Gateway API / Kong style)
    http = spec.get("http", {}) or {}
    if isinstance(http, dict):
        routes = http.get("routes", []) or http.get("route", [])
        if routes:
            for route in routes:
                if isinstance(route, dict):
                    # Look for target URL/host in route actions
                    targets = route.get("targets", []) or route.get("target", [])
                    if targets:
                        if isinstance(targets, list) and targets:
                            target = targets[0]
                        else:
                            target = targets
                        if isinstance(target, dict):
                            return target.get("host", target.get("url", target.get("address", "")))
                    # Look for action URL
                    action = route.get("action", {})
                    if isinstance(action, dict):
                        return action.get("url", action.get("host", ""))
                    # Look for upstream URL
                    upstreams = route.get("upstreams", []) or route.get("upstream", [])
                    if upstreams:
                        if isinstance(upstreams, list) and upstreams:
                            up = upstreams[0]
                        else:
                            up = upstreams
                        if isinstance(up, dict):
                            return up.get("url", up.get("host", up.get("address", "")))

        ups = http.get("ups", [])
        if ups:
            for up in ups:
                if isinstance(up, dict):
                    url = up.get("url", up.get("host", up.get("address", "")))
                    if url:
                        return url

    # Pattern 3: spec.rules (like Ingress)
    rules = spec.get("rules", [])
    if rules:
        for rule in rules:
            if isinstance(rule, dict):
                host = rule.get("host", "")
                paths = rule.get("paths", [])
                if host:
                    return host
                if paths:
                    for path in paths:
                        if isinstance(path, dict):
                            backend = path.get("backend", {})
                            if isinstance(backend, dict):
                                svc = backend.get("service", {})
                                if isinstance(svc, dict):
                                    return svc.get("host", svc.get("url", ""))

    return ""


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
        logging.info("No dashy annotations found – keeping existing config")
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
