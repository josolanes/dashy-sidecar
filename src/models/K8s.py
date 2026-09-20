#!/usr/bin/env python3

import yaml
import os
from typing import Dict, List, Optional, Any

from dataclasses import dataclass, field
from kubernetes import client, config

from src.models.Url import Url

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


class K8s:
    HAS_K8S = False
    logging = None

    def __init__(self, logging):
        self.logging = logging

    @staticmethod
    def extract_k8s_meta(k8annotations: Optional[Dict[str, str]]) -> K8sMeta:
        """Extract dashy metadata from a Kubernetes resource's annotation dict.

        Supports two annotation formats:

        1. Flat format (existing):
            dashy.title: My Service
            dashy.url: https://example.com

        2. YAML block format (new):
            dashy: |
              section: Services
              title: My Service
              url: https://example.com
        """
        if not k8annotations:
            return K8sMeta()

        # --- Attempt YAML block format first ---
        dashy_block = k8annotations.get("dashy")
        if dashy_block:
            try:
                parsed = yaml.safe_load(dashy_block)
                if isinstance(parsed, dict):
                    return K8sMeta(
                        title=str(parsed.get("title", "")),
                        description=str(parsed.get("description", "")),
                        url=str(parsed.get("url", "")),
                        icon=str(parsed.get("icon", "")),
                        section=str(parsed.get("section", "")),
                    )
            except yaml.YAMLError:
                pass

        # --- Fall back to flat format ---
        return K8sMeta(
            title=k8annotations.get("dashy.title", ""),
            description=k8annotations.get("dashy.description", ""),
            url=k8annotations.get("dashy.url", ""),
            icon=k8annotations.get("dashy.icon", ""),
            section=k8annotations.get("dashy.section", ""),
        )

    def collect_services(self) -> List[K8sItem]:
        """Collect all Services with dashy annotations."""
        if not self.HAS_K8S:
            return []

        try:
            core = client.CoreV1Api()
            items: List[K8sItem] = []
            for svc in core.list_service_for_all_namespaces().items:
                meta = self.extract_k8s_meta(svc.metadata.annotations)
                if not meta.title:
                    continue
                if meta.title or meta.description or meta.url or meta.icon:
                    items.append(K8sItem(
                        name=svc.metadata.name,
                        namespace=svc.metadata.namespace,
                        kind="Service",
                        meta=meta,
                    ))
            return items
        except Exception as e:
            self.logging.warning("Failed to list Services: %s", e)
            return []

    def collect_ingresses(self) -> List[K8sItem]:
        """Collect all Ingresses with dashy annotations."""
        if not self.HAS_K8S:
            return []

        try:
            net = client.NetworkingV1Api()
            items: List[K8sItem] = []
            for ing in net.list_ingress_for_all_namespaces().items:
                meta = K8s.extract_k8s_meta(ing.metadata.annotations)
                if not meta.title:
                    continue
                if meta.title or meta.description or meta.url or meta.icon:
                    items.append(K8sItem(
                        name=ing.metadata.name,
                        namespace=ing.metadata.namespace,
                        kind="Ingress",
                        meta=meta,
                    ))
            return items
        except Exception as e:
            self.logging.warning("Failed to list Ingresses: %s", e)
            return []

    def collect_ingress_routes(self) -> List[K8sItem]:
        """
        Collect IngressRoute custom resources (Gateway API / Kong CRD).

        Uses the dynamic client to query IngressRoute resources from all
        namespaces. Supports both gateway.networking.k8s.io IngressRoute and
        any other custom resources whose kind is "IngressRoute".
        """
        if not self.HAS_K8S:
            return []

        try:
            from kubernetes import dynamic
        except ImportError:
            self.logging.warning("kubernetes.dynamic not available – skipping IngressRoute collection")
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
                # noinspection PyBroadException
                try:
                    resp = ingress_route_resource.get(namespace=ns)
                    for ir in resp.get("items", []):
                        meta_obj = ir.get("metadata", {})
                        raw_annotations = meta_obj.get("annotations", {})
                        meta = K8s.extract_k8s_meta(raw_annotations)

                        # If no dashy.url, try to derive from IngressRoute spec
                        url = meta.url
                        if not url:
                            url = self.extract_ingress_route_url(ir)

                        if not meta.title:
                            continue

                        items.append(K8sItem(
                            name=meta_obj.get("name", ""),
                            namespace=ns,
                            kind="IngressRoute",
                            meta=K8sMeta(
                                title=meta.title,
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
            self.logging.warning("Failed to list IngressRoutes: %s", e)
            return []

    def load_k8s_config(self):
        try:
            config.load_incluster_config()
            self.logging.info("Using in-cluster config")
        except config.ConfigException:
            kubeconf = os.environ.get("KUBECONFIG", "")
            if kubeconf:
                config.load_kube_config(kubeconf)
                self.logging.info(f"Using kubeconfig: {kubeconf}")
            else:
                config.load_kube_config()
                self.logging.info("Using default kubeconfig")

    @staticmethod
    def extract_ingress_route_url(ir: Dict[str, Any]) -> str:
        """
        Try to extract a URL from an IngressRoute resource's spec.

        Supports multiple common IngressRoute CRD formats:
        - Traefik: spec.routes.0.match -> Host(`hostname`) with auto-scheme
        - Gateway API: spec.http.routes.action(s).target(s)
        - Kong: spec.http.routes[*].upstream(s) or spec.http.ups[*]
        - Generic: Any top-level 'url' or 'host' field in spec
        """
        spec = ir.get("spec", {}) or {}

        # Try common patterns
        # Pattern 1: spec.url or spec.host
        if spec.get("url"):
            url = str(spec["url"])
            return Url.auto_detect_scheme(url)
        if spec.get("host"):
            url = str(spec["host"])
            return Url.auto_detect_scheme(url)

        # Pattern 1b: spec.routes[0].match (Traefik standard)
        routes = spec.get("routes", [])
        if routes and isinstance(routes, list) and routes:
            first_route = routes[0]
            if isinstance(first_route, dict):
                match_str = first_route.get("match", "")
                if match_str:
                    hostname = Url.extract_url_from_match(match_str)
                    if hostname:
                        return Url.auto_detect_scheme(hostname)

        # Pattern 2: spec.http (Gateway API / Kong style)
        http = spec.get("http", {}) or {}
        if isinstance(http, dict):
            http_routes = http.get("routes", []) or http.get("route", [])
            if http_routes:
                for route in http_routes:
                    if isinstance(route, dict):
                        # Look for target URL/host in route actions
                        targets = route.get("targets", []) or route.get("target", [])
                        if targets:
                            if isinstance(targets, list) and targets:
                                target = targets[0]
                            else:
                                target = targets
                            if isinstance(target, dict):
                                return Url.auto_detect_scheme(
                                    target.get("host", target.get("url", target.get("address", "")))
                                )
                        # Look for action URL
                        action = route.get("action", {})
                        if isinstance(action, dict):
                            return Url.auto_detect_scheme(
                                action.get("url", action.get("host", ""))
                            )
                        # Look for upstream URL
                        upstreams = route.get("upstreams", []) or route.get("upstream", [])
                        if upstreams:
                            if isinstance(upstreams, list) and upstreams:
                                up = upstreams[0]
                            else:
                                up = upstreams
                            if isinstance(up, dict):
                                return Url.auto_detect_scheme(
                                    up.get("url", up.get("host", up.get("address", "")))
                                )

            ups = http.get("ups", [])
            if ups:
                for up in ups:
                    if isinstance(up, dict):
                        url = up.get("url", up.get("host", up.get("address", "")))
                        if url:
                            return Url.auto_detect_scheme(url)

        # Pattern 3: spec.rules (like Ingress)
        rules = spec.get("rules", [])
        if rules:
            for rule in rules:
                if isinstance(rule, dict):
                    host = rule.get("host", "")
                    paths = rule.get("paths", [])
                    if host:
                        return Url.auto_detect_scheme(host)
                    if paths:
                        for path in paths:
                            if isinstance(path, dict):
                                backend = path.get("backend", {})
                                if isinstance(backend, dict):
                                    svc = backend.get("service", {})
                                    if isinstance(svc, dict):
                                        return Url.auto_detect_scheme(
                                            svc.get("host", svc.get("url", ""))
                                        )

        return ""