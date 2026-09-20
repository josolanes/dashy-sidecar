#!/usr/bin/env python3

import re

from typing import Optional

class Url:
    @staticmethod
    def extract_url_from_match(match_str: str) -> Optional[str]:
        """
        Extract the first hostname from a Traefik IngressRoute match rule.

        Traefik match rules look like:
          Host(`example.com`) || Host(`www.example.com`)

        This function extracts the first quoted hostname.
        """
        if not match_str:
            return None
        # Match Host(`...`) or Host('...')
        m = re.search(r"Host\([`\']([^`\']+)[`\']\)", match_str)
        if m:
            return m.group(1)
        return None


    @staticmethod
    def auto_detect_scheme(url: str) -> str:
        """
        Determine whether to use http or https for the given URL and return a
        complete URL with the appropriate scheme.

        If the host ends with .local, .internal, is an IP address, or otherwise
        implicitly represents a local URL, assume http. Otherwise, assume https.

        If the URL already has an explicit scheme prefix, return it unchanged.
        If a scheme is missing, prepend the auto-detected scheme.
        """
        if not url:
            return ""

        # If the URL already has an explicit scheme, return as-is
        if url.startswith("http://") or url.startswith("https://"):
            return url

        # Determine the scheme
        scheme = "http" if Url.is_local_url(url) else "https"

        # Prepend the scheme
        return f"{scheme}://{url}"


    @staticmethod
    def is_local_url(url: str) -> bool:
        """Check if a URL (host portion) is implicitly local."""
        # Extract the host portion
        host = url
        # Remove leading path separators or dots
        host = host.lstrip("/").lstrip(".")
        # Split on first / to get host from a full URL without scheme
        host = host.split("/")[0]

        # Check for .local, .internal suffixes
        host_lower = host.lower()
        if host_lower.endswith(".local") or host_lower.endswith(".internal"):
            return True

        # Strip port number if present (e.g., 192.168.1.1:8080 -> 192.168.1.1)
        ip_host = host.split(":")[0]

        # Check for IP addresses (IPv4)
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip_host):
            return True

        # Check for [IPv6] addresses
        if host.startswith("[") and "]" in host:
            return True

        return False