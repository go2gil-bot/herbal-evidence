"""Outbound HTTP for literature providers, with the door bolted.

Everything this service fetches from the internet goes through here. The rules
are deliberately strict because the alternative - a URL that eventually comes
from a source record, a redirect, or a model - is exactly how a server ends up
fetching its own metadata endpoint.

  * only hosts on the allowlist, matched exactly
  * https only
  * redirects are NOT followed; a redirect is an answer, not an instruction
  * bounded timeout and bounded download size
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("herbal_evidence.research.http")

ALLOWED_HOSTS = frozenset(
    {
        "eutils.ncbi.nlm.nih.gov",  # PubMed E-utilities
        "www.ebi.ac.uk",  # Europe PMC REST
    }
)

TIMEOUT_SECONDS = 20.0
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "HerbalEvidence/0.1 (research platform; contact configured per deployment)"


class FetchRefused(Exception):
    """The request was not allowed to leave. Never a network failure."""


class FetchFailed(Exception):
    """The request left and did not come back usable."""


def _assert_public_address(host: str) -> None:
    """Refuse a host that resolves into private space.

    An allowlisted name should never point at 127.0.0.1 or a link-local
    metadata address, but DNS is not ours and this is cheap.
    """
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchFailed(f"cannot resolve {host}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise FetchRefused(f"{host} resolves to a non-public address")


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise FetchRefused(f"refused scheme {parsed.scheme!r}; https only")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise FetchRefused(f"refused host {parsed.hostname!r}; not an allowed provider")
    _assert_public_address(parsed.hostname)


async def get(url: str, params: dict | None = None) -> httpx.Response:
    check_url(url)

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc

    if response.is_redirect:
        raise FetchFailed(f"provider redirected to {response.headers.get('location', '?')}")
    if response.status_code >= 400:
        raise FetchFailed(f"provider returned {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise FetchFailed("response exceeded the size limit")

    return response
