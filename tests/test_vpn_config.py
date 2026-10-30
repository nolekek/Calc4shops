import pytest
from app.core.vpn_config import (
    parse_vless_uri,
    parse_shadowsocks_uri,
    parse_vpn_key_to_singbox,
)
from app.config import Settings


def test_parse_vless_reality_uri():
    uri = "vless://12345678-1234-1234-1234-123456789abc@vpn.sota.example:443?security=reality&sni=gateway.example.com&fp=chrome&pbk=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789&sid=12345678&type=tcp&flow=xtls-rprx-vision#Sota-Server"
    out = parse_vless_uri(uri)

    assert out["type"] == "vless"
    assert out["server"] == "vpn.sota.example"
    assert out["server_port"] == 443
    assert out["uuid"] == "12345678-1234-1234-1234-123456789abc"
    assert out["flow"] == "xtls-rprx-vision"
    assert out["tls"]["enabled"] is True
    assert out["tls"]["server_name"] == "gateway.example.com"
    assert out["tls"]["reality"]["public_key"] == "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def test_parse_shadowsocks_uri():
    # base64 of 'aes-256-gcm:secretpass' is 'YWVzLTI1Ni1nY206c2VjcmV0cGFzcw=='
    uri = "ss://YWVzLTI1Ni1nY206c2VjcmV0cGFzcw==@node1.sota.example:8388#Sota-Shadowsocks"
    out = parse_shadowsocks_uri(uri)

    assert out["type"] == "shadowsocks"
    assert out["server"] == "node1.sota.example"
    assert out["server_port"] == 8388
    assert out["method"] == "aes-256-gcm"
    assert out["password"] == "secretpass"


def test_generate_singbox_structure():
    uri = "vless://11111111-2222-3333-4444-555555555555@edge.sota.example:8443?security=reality&sni=yahoo.com&fp=chrome&pbk=key123&type=tcp#SotaNode"
    cfg = parse_vpn_key_to_singbox(uri)

    assert "inbounds" in cfg
    assert cfg["inbounds"][0]["listen_port"] == 1080
    assert cfg["inbounds"][0]["type"] == "mixed"
    assert len(cfg["outbounds"]) == 2
    assert cfg["outbounds"][0]["type"] == "vless"


def test_settings_proxy_resolution():
    s1 = Settings(SOTA_VPN_KEY=None, TELEGRAM_PROXY_URL=None)
    assert s1.get_telegram_proxy() is None

    s2 = Settings(SOTA_VPN_KEY="socks5://user:pass@1.2.3.4:1080")
    assert s2.get_telegram_proxy() == "socks5://user:pass@1.2.3.4:1080"

    s3 = Settings(SOTA_VPN_KEY="vless://test@1.1.1.1:443?security=none#test")
    assert "1080" in s3.get_telegram_proxy()
