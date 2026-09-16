#!/usr/bin/env python3

from dataclasses import dataclass, field

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