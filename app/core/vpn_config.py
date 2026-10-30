import re
import json
import base64
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any


def b64_decode_safe(s: str) -> str:
    """Декодирует base64 с автоматическим дополнением padding."""
    s = s.strip()
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    return base64.urlsafe_b64decode(s.encode()).decode("utf-8", errors="ignore")


def parse_shadowsocks_uri(uri: str) -> Dict[str, Any]:
    """Парсит Shadowsocks / Outline URI (ss://...)."""
    parsed = urllib.parse.urlparse(uri)
    tag = urllib.parse.unquote(parsed.fragment) if parsed.fragment else "sotavpn-out"
    
    server = parsed.hostname
    port = parsed.port
    method = None
    password = None

    if parsed.username:
        # Format: ss://BASE64@server:port
        decoded_userinfo = b64_decode_safe(parsed.username)
        if ":" in decoded_userinfo:
            method, password = decoded_userinfo.split(":", 1)
        else:
            method = decoded_userinfo
            password = parsed.password or ""
    elif parsed.netloc and not server:
        # Format: ss://BASE64_OF_METHOD_PASS_SERVER_PORT#tag
        decoded = b64_decode_safe(parsed.netloc)
        # decoded looks like method:password@server:port
        match = re.match(r"^(.*?):(.*?)@(.*):(\d+)$", decoded)
        if match:
            method, password, server, port_str = match.groups()
            port = int(port_str)

    if not server or not port:
        raise ValueError(f"Не удалось извлечь хост/порт из Shadowsocks URI: {uri}")

    return {
        "type": "shadowsocks",
        "tag": tag,
        "server": server,
        "server_port": port,
        "method": method or "chacha20-ietf-poly1305",
        "password": password or "",
    }


def parse_vless_uri(uri: str) -> Dict[str, Any]:
    """Парсит VLESS / VLESS Reality URI (vless://...)."""
    parsed = urllib.parse.urlparse(uri)
    tag = urllib.parse.unquote(parsed.fragment) if parsed.fragment else "sotavpn-out"
    
    uuid = parsed.username
    server = parsed.hostname
    port = parsed.port or 443
    
    query = urllib.parse.parse_qs(parsed.query)
    security = query.get("security", ["none"])[0].lower()
    sni = query.get("sni", [query.get("server_name", [server])[0]])[0]
    fp = query.get("fp", ["chrome"])[0]
    pbk = query.get("pbk", [""])[0]
    sid = query.get("sid", [""])[0]
    flow = query.get("flow", [""])[0]
    network_type = query.get("type", ["tcp"])[0].lower()

    outbound: Dict[str, Any] = {
        "type": "vless",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "network": network_type,
    }

    if flow:
        outbound["flow"] = flow

    if security in ["reality", "tls"]:
        tls_config: Dict[str, Any] = {
            "enabled": True,
            "server_name": sni,
            "utls": {
                "enabled": True,
                "fingerprint": fp
            }
        }
        if security == "reality" and pbk:
            tls_config["reality"] = {
                "enabled": True,
                "public_key": pbk,
                "short_id": sid
            }
        outbound["tls"] = tls_config

    return outbound


def parse_vpn_key_to_singbox(key_str: str) -> Dict[str, Any]:
    """Преобразует строку ключа (VLESS, SS, Trojan) в конфигурацию sing-box."""
    key = key_str.strip()

    if key.startswith("vless://"):
        outbound = parse_vless_uri(key)
    elif key.startswith("ss://"):
        outbound = parse_shadowsocks_uri(key)
    else:
        raise ValueError("Неподдерживаемый формат ключа. Ожидается vless:// или ss://")

    config = {
        "log": {
            "level": "warn"
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "0.0.0.0",
                "listen_port": 1080
            }
        ],
        "outbounds": [
            outbound,
            {
                "type": "direct",
                "tag": "direct"
            }
        ]
    }
    return config


def generate_singbox_config_file(key_str: str, output_file: str) -> bool:
    """Генерирует файл sing-box конфигурации на диске."""
    try:
        config_data = parse_vpn_key_to_singbox(key_str)
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error generating singbox config: {e}")
        return False


if __name__ == "__main__":
    import os
    import sys
    from app.config import settings

    key = settings.SOTA_VPN_KEY or os.environ.get("SOTA_VPN_KEY")
    if not key:
        print("No SOTA_VPN_KEY provided. Skipping tunnel config generation.")
        sys.exit(0)

    target_file = sys.argv[1] if len(sys.argv) > 1 else "./data/singbox_config.json"
    ok = generate_singbox_config_file(key, target_file)
    if ok:
        print(f"Successfully generated sing-box tunnel config at {target_file}")
    else:
        sys.exit(1)
