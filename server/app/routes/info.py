from __future__ import annotations

import socket
from typing import List

from fastapi import APIRouter

router = APIRouter(prefix="/info", tags=["info"])


def _primary_local_ip() -> str:
    # Best-effort method to get the primary outbound IP address
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # doesn't actually send data
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _all_local_ips() -> List[str]:
    ips = set()
    # try primary ip first
    primary = _primary_local_ip()
    if primary and not primary.startswith("127."):
        ips.add(primary)

    # try resolving hostname
    try:
        hostname = socket.gethostname()
        for res in socket.getaddrinfo(hostname, None):
            af, socktype, proto, canonname, sa = res
            ip = sa[0]
            if ip and not ip.startswith("127.") and ":" not in ip:
                ips.add(ip)
    except Exception:
        pass

    return list(ips) or [primary]


@router.get("/")
def info() -> dict:
    ips = _all_local_ips()
    port = 8000
    urls = [f"http://{ip}:{port}/" for ip in ips]
    return {"ips": ips, "port": port, "urls": urls}
