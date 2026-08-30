# dashy-sidecar

A Kubernetes sidecar container that automatically generates and maintains a [Dashy](https://github.com/Lissy93/dashy) ``conf.yml`` configuration file from Kubernetes resource annotations.

Monitors **Services**, **Ingresses**, and **IngressRoutes** across all namespaces for ``dashy.*`` metadata annotations, groups them into sections, and writes the resulting YAML to a shared config file that the Dashy container reads.

## Quick Start

Mount a shared ``config`` volume between your Dashy pod and the dashy-sidecar sidecar, then annotate your Kubernetes resources:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: jellyfin
  namespace: media
  annotations:
    dashy.title: Jellyfin
    dashy.url: https://jellyfin.example.com
    dashy.section: Media & Entertainment
    dashy.description: Media streaming server
    dashy.icon: hl-jellyfin
```

***OR***

```yaml
apiVersion: v1
kind: Service
metadata:
  name: jellyfin
  namespace: media
  annotations:
    dashy: |
      title: Jellyfin
      url: https://jellyfin.example.com
      section: Media & Entertainment
      description: Media streaming server
      icon: hl-jellyfin
```

The sidecar watches for annotation changes every ``SYNC_INTERVAL`` seconds (default: ``60s``) and updates the config file. Dashy reads the same file and reflects the current state.

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dashy
spec:
  template:
    spec:
      volumes:
        - name: config
          emptyDir: {}
      containers:
        - name: dashy
          image: lissy93/dashy
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /app/user-data/
        - name: dashy-sidecar
          image: josolanes/dashy-sidecar:latest
          volumeMounts:
            - name: config
              mountPath: /app/user-data/
          env:
            - name: DASHY_CONF
              value: /app/user-data/conf.yml
            - name: SYNC_INTERVAL
              value: "60"
```

## Supported Resource Types

The sidecar watches the following Kubernetes resource kinds across **all namespaces**:

| Kind           | API Group                          | Notes                                         |
|----------------|------------------------------------|-------------------------------------------------|
| ``Service``      | ``v1``                               | Standard core Services                          |
| ``Ingress``      | ``networking.k8s.io/v1``             | Standard Networking v1 Ingresses                |
| ``IngressRoute`` | Any custom resource                | Gateway API / Kong CRD / any ``IngressRoute`` kind |

Only resources with a ``dashy.title`` (or ``title`` in the YAML block) annotation are collected.

## Annotations

### Flat Format (Simple)

Use individual ``dashy.*`` annotations on a resource:

```yaml
metadata:
  annotations:
    dashy.title: "My Service"
    dashy.url: "https://example.com"
    dashy.section: "Services"
    dashy.description: "A description of the service"
    dashy.icon: "fas fa-server"
```

| Annotation                    | Required | Description                                          |
|-------------------------------|----------|------------------------------------------------------|
| ``dashy.title``                 | Yes      | Display name for the item in Dashy                   |
| ``dashy.url``                   | No       | URL / link the item points to                        |
| ``dashy.section``               | No       | Dashy section name. Items are grouped by this value. |
| ``dashy.description``           | No       | Description shown in the item card                   |
| ``dashy.icon``                  | No       | Icon class (FontAwesome, Material, etc.)             |

### YAML Block Format

For cleaner multi-line annotations, use a single ``dashy`` key with an inline YAML block. **This format takes priority over the flat format** when both are present:

```yaml
metadata:
  annotations:
    dashy: |
      title: My Service
      url: https://example.com
      section: Services
      description: A description
      icon: fas fa-server
```

## Sections

Resources sharing the same ``dashy.section`` value are grouped into a single Dashy section. Resources with an empty or missing ``dashy.section`` are placed under an ``"Unnamed"`` section.

### Default Section Icons

Certain section names get auto-assigned icons:

| Section Name                | Icon                              |
|-----------------------------|-----------------------------------|
| ``Media & Entertainment``     | ``fas fa-photo-video``              |
| ``Networking``                | ``fas fa-network-wired``            |
| ``Network Monitoring``        | ``fas fa-tachometer-alt-fast``      |
| ``System Monitoring``         | ``fas fa-monitor-heart-rate``       |
| ``Home Control``              | ``fas fa-house-signal``             |
| ``Productivity``              | ``fas fa-bookmark``                 |

Any other section name gets the default ``fas fa-folder`` icon.

## IngressRoute URL Extraction

For ``IngressRoute`` custom resources that lack an explicit ``dashy.url``, the sidecar attempts to derive one from the resource's spec. It checks multiple common patterns:

- ``spec.url`` or ``spec.host``
- ``spec.http.routes[*].targets[*].host`` (Gateway API / Kong style)
- ``spec.http.routes[*].action.url``
- ``spec.http.ups[*].url``
- ``spec.rules[*].host``

## Environment Variables

| Variable         | Default              | Description                      |
|------------------|----------------------|----------------------------------|
| ``DASHY_CONF``     | ``/app/user-data/conf.yml`` | Path to the Dashy config file  |
| ``SYNC_INTERVAL``  | ``60``                 | Seconds between config syncs    |
| ``KUBECONFIG``     | (in-cluster)         | Path to a kubeconfig file       |

## CLI Arguments

The sidecar binary supports the following flags (which also map to environment variables above):

```
--conf           Path to Dashy conf.yml
--interval       Sync interval in seconds (default: 60)
--kubeconfig     Path to kubeconfig file
-v, --verbose    Enable verbose (debug) logging
```

## Existing Config Preservation

The sidecar **preserves** all existing fields in the Dashy config file — ``pageInfo``, ``appConfig``, ``navLinks``, etc. — and only replaces the ``sections`` array. This means you can use a base ``conf.yml`` to configure themes, custom colors, error reporting, and other Dashy settings, while the sidecar manages the section/item layout automatically.

## Health Check

The sidecar exposes a health check endpoint on port **8081**:

```
GET http://<pod-ip>:8081/healthz
```

This can be used in Kubernetes ``livenessProbe`` or ``readinessProbe`` configurations.

## Example: Full Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dashy
spec:
  template:
    spec:
      volumes:
        - name: config
          emptyDir: {}
      containers:
        - name: dashy
          image: lissy93/dashy:latest
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: config
              mountPath: /app/user-data/
        - name: dashy-sidecar
          image: josolanes/dashy-sidecar:latest
          env:
            - name: DASHY_CONF
              value: /app/user-data/conf.yml
            - name: SYNC_INTERVAL
              value: "30"
          volumeMounts:
            - name: config
              mountPath: /app/user-data/
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8081
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8081
            initialDelaySeconds: 5
            periodSeconds: 5
```

```yaml
# Example: annotated Services
apiVersion: v1
kind: Service
metadata:
  name: jellyfin
  namespace: default
  annotations:
    dashy: |
      title: Jellyfin
      url: https://jellyfin.example.com
      section: Media & Entertainment
      description: Media streaming
      icon: hl-jellyfin
spec:
  ports:
    - port: 8096
---
apiVersion: v1
kind: Service
metadata:
  name: pihole
  namespace: default
  annotations:
    dashy.title: Pi-hole
    dashy.url: https://pihole.example.com
    dashy.section: Networking
    dashy.icon: hl-pihole
spec:
  ports:
    - port: 80
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    dashy.title: Grafana
    dashy.url: https://grafana.example.com
    dashy.section: Network Monitoring
    dashy.description: Metrics dashboard
    dashy.icon: fas fa-chart-line
```

This produces a Dashy config with three sections — **Media & Entertainment** (Jellyfin), **Networking** (Pi-hole), and **Network Monitoring** (Grafana) — automatically maintained as you add, remove, or modify annotated resources.

## Build & Run Locally

```bash
pip install -r requirements.txt
python3 main.py --conf ./conf.yml --interval 30
```

Or build a Docker image:

```bash
docker build -t dashy-sidecar .
```
```