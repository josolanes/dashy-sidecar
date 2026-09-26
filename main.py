#!/usr/bin/env python3
from __future__ import annotations

"""
Kubernetes sidecar for Dashy.

Monitors Kubernetes Services, Ingresses, and IngressRoutes (Gateway API / Traefik)
for dashy metadata annotations and updates a Dashy conf.yml file with appropriate
sections and items.

Two annotation formats are supported:

1. Flat format:
    dashy.title: My Service
    dashy.url: https://example.com
    dashy.section: Services
    dashy.description: A cool service
    dashy.icon: hl-myicon

2. YAML block format:
    dashy: |
      section: Services
      title: My Service
      url: https://example.com
      section: Services
      description: A cool service
      icon: hl-myicon

Usage:
    python3 main.py [--conf /app/user-data/conf.yml] [--interval 60] [--kubeconfig ~/.kube/config]

Environment variables:
    DASHY_CONF   - path to conf.yml (default: /app/user-data/conf.yml)
    SYNC_INTERVAL - sync interval in seconds (default: 60)
    KUBECONFIG   - path to kubeconfig (default: in-cluster)
"""

import sys
import argparse
import logging
import os
import signal
import threading
from typing import List
from logging import exception

# ---------------------------------------------------------------------------
# K8s client (optional – graceful degradation)
# ---------------------------------------------------------------------------

try:
    # noinspection PyUnusedImports
    from src.K8s import K8s, K8sItem, K8sMeta
    # noinspection PyUnusedImports
    from src.Sidecar import SidecarConfig, Sidecar
    # noinspection PyUnusedImports
    from src.Dashy import Dashy, DashyConfig

    sidecar = Sidecar(logging)
    k8s = K8s(logging)
    dashy = Dashy(logging)
    k8s.HAS_K8S = True
except ImportError:
    sidecar = Sidecar(logging)
    k8s = K8s(logging)
    dashy = Dashy(logging)
    k8s.HAS_K8S = False


# ---------------------------------------------------------------------------
# Kubernetes collectors
# ---------------------------------------------------------------------------


def collect_all() -> List[K8sItem]:
    """Collect items from all supported Kubernetes resource types."""
    all_items: List[K8sItem] = []

    for fn in [k8s.collect_services, k8s.collect_ingresses, k8s.collect_ingress_routes]:
        try:
            items = fn()
            logging.info(f"  {fn.__name__}: {len(items)} items")
            all_items.extend(items)
        except Exception as e:
            logging.warning(f"  {fn.__name__}: {e}")

    return all_items


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(dashy_conf_path: str, sidecar_conf_path: str, interval: int) -> None:
    """Main sync loop."""
    logging.info("Starting Dashy sidecar")
    logging.info("  Dashy config path : %s", dashy_conf_path)
    logging.info("  Sidecar config path : %s", sidecar_conf_path)
    logging.info("  Sync interval: %ds", interval)

    if not k8s.HAS_K8S:
        logging.error("kubernetes Python library not installed – cannot sync")
        sys.exit(1)

    # Try to load in-cluster or kubeconfig
    try:
        k8s.load_k8s_config()
    except exception as e:
        logging.error("Cannot load Kubernetes config: %s", e)
        sys.exit(1)

    sidecar_conf = sidecar.load_config(sidecar_conf_path)

    # Initial sync
    dashy.sync(dashy_conf_path, collect_all(), sidecar_conf)

    # Periodic sync
    timer = threading.Timer(interval, run_loop, [dashy_conf_path, sidecar_conf_path, interval])
    timer.daemon = True
    timer.start()

    # Block on SIGTERM
    signal.pause()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Kubernetes sidecar for Dashy")

    parser.add_argument("--dashy-conf",
                        default=os.environ.get("DASHY_CONF", "/app/user-data/conf.yml"),
                        help="Path to Dashy conf.yml")
    parser.add_argument("--sidecar-conf",
                        default=os.environ.get("SIDECAR_CONF", "/app/user-data/sidecar.yml"),
                        help="Path to Sidecar conf.yml")
    parser.add_argument("--interval",
                        type=int,
                        default=int(os.environ.get("SYNC_INTERVAL", "60")),
                        help="Sync interval in seconds (default: 60)")
    parser.add_argument("--kubeconfig",
                        default=os.environ.get("KUBECONFIG", ""),
                        help="Path to kubeconfig file")
    parser.add_argument("-v", "--verbose",
                        action="store_true",
                        help="Verbose logging")

    args = parser.parse_args()

    if args.kubeconfig:
        os.environ["KUBECONFIG"] = args.kubeconfig

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout
    )

    run_loop(args.dashy_conf, args.sidecar_conf, args.interval)


if __name__ == "__main__":
    main()
