"""
web/security_utils.py
Helpers de seguridad chicos y compartidos entre rutas/motor de extracción —
sin dependencias de Flask, para poder testear sin contexto de request/app.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def url_webhook_es_segura(url: str) -> bool:
    """Bloquea SSRF en la URL de Webhook de alertas (Configuracion.webhook_url):
    solo esquema http/https, y el hostname debe resolver a una IP que NO sea
    loopback/link-local/reservada/multicast -- corta el pivote hacia el endpoint de
    metadata de nube (169.254.169.254) o localhost del propio servidor. Deja pasar
    rangos privados RFC1918 a propósito: un Webhook interno (Teams/Slack self-hosted,
    gateway propio) en la red corporativa es un uso legítimo, y el endpoint que guarda
    esta URL ya quedó restringido a admin (hallazgo de seguridad, corregido 2026-09-07).

    Falla cerrado: cualquier error de parseo/resolución de DNS devuelve False."""
    try:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
        if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
        return True
    except Exception:
        return False


def normalizar_username(raw: str) -> str:
    """Username 'pelado': sin dominio NetBIOS (DOMINIO\\usuario) ni UPN (usuario@dominio).
    Mismo criterio usado en 6+ lugares del pipeline de extracción (Horizon, App Volumes,
    matching AD) -- unificado acá para no repetir el split a mano en cada archivo
    (limpieza de duplicación, 2026-09-07)."""
    if not raw:
        return ""
    return raw.strip().split("\\")[-1].split("@")[0]
