"""Fichiers de déploiement HTTPS (option `docker-compose.tls.yml`) : contrôles statiques, car aucun Docker n'est disponible pour les lancer en CI.

Ce qui peut casser en silence : le sous-réseau de confiance de nginx qui ne correspond plus à celui de Compose (le limiteur de connexions verrait alors une seule IP, ou
pire accorderait sa confiance à une plage trop large), une image non épinglée, le port de nginx publié en plus de celui de Caddy.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TLS = (ROOT / "docker-compose.tls.yml").read_text(encoding="utf-8")
BASE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
REALIP = (ROOT / "deploy" / "realip.conf").read_text(encoding="utf-8")
CADDY = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
ENV = (ROOT / ".env.example").read_text(encoding="utf-8")


def test_nginx_trusts_exactly_the_compose_subnet():
    compose = re.findall(r"subnet:\s*([0-9./]+)", TLS)
    trusted = re.findall(r"set_real_ip_from\s+([0-9./]+);", REALIP)
    assert compose and trusted == compose and len(trusted) == 1
    assert re.fullmatch(r"172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+/(2[4-9]|30)", trusted[0])         # un /24 privé, jamais une plage large ni 0.0.0.0/0


def test_real_ip_uses_the_forwarded_header_without_recursion():
    assert "real_ip_header X-Forwarded-For;" in REALIP and "real_ip_recursive off;" in REALIP
    assert "0.0.0.0" not in REALIP and "/0" not in REALIP


def test_the_proxy_image_is_pinned_to_a_version():
    images = re.findall(r"image:\s*(\S+)", TLS)
    assert images and all(re.search(r":\d+\.\d+", i) and "latest" not in i for i in images)


def test_caddy_terminates_tls_with_the_internal_authority_and_does_not_buffer():
    assert "tls internal" in CADDY and "reverse_proxy web:80" in CADDY and "flush_interval -1" in CADDY and "admin off" in CADDY
    assert "{$KAJI_TLS_SITE}" in CADDY


def test_only_caddy_publishes_a_port_in_the_tls_override_and_nginx_stays_local_by_default():
    assert "web:" in TLS and re.search(r"ports:\s*\n\s*-\s*\"\$\{KAJI_TLS_BIND", TLS)
    web_block = TLS.split("\n  web:")[1].split("\n# ")[0]
    assert "ports:" not in web_block                                                           # nginx ne publie rien de plus
    assert '"${KAJI_BIND:-127.0.0.1}:${KAJI_PORT:-8080}:80"' in BASE                           # et son port reste local par défaut


def test_caddy_waits_for_nginx_and_mounts_the_config_read_only():
    assert re.search(r"depends_on:\s*\n\s*web:\s*\n\s*condition: service_healthy", TLS)
    assert "./deploy/Caddyfile:/etc/caddy/Caddyfile:ro" in TLS and "./deploy/realip.conf:/etc/nginx/conf.d/realip.conf:ro" in TLS


def test_caddy_has_a_default_sni_so_that_an_ip_address_works():
    """Constaté en réel (2026-11-13) : ouvert par une adresse IP, le navigateur n'envoie pas de SNI et Caddy (dans Docker) ne trouvait aucun certificat."""
    assert re.search(r"^\s*default_sni \{\$KAJI_TLS_HOST\}$", CADDY, re.M)
    assert re.search(r"^\s*KAJI_TLS_HOST: \$\{KAJI_TLS_HOST:-localhost\}", TLS, re.M)
    assert "KAJI_TLS_HOST" in ENV


def test_env_example_documents_the_new_settings_and_keeps_the_safe_defaults():
    for name in ("KAJI_SETUP_TOKEN", "KAJI_TLS_SITE", "KAJI_TLS_PORT"):
        assert name in ENV
    assert re.search(r"^KAJI_COOKIE_SECURE=true$", ENV, re.M) and re.search(r"^KAJI_BIND=127\.0\.0\.1$", ENV, re.M)
    assert re.search(r"^KAJI_SETUP_TOKEN=$", ENV, re.M)                                        # vide par défaut : comportement inchangé
