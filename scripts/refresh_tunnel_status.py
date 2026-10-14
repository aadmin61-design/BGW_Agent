"""读取当前隧道实例的网址并核验；不重启服务，不调用模型或修改知识库。"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
SERVICE = "cloudflared-quick.service"


def systemctl_value(property_name):
    return subprocess.check_output(
        ["systemctl", "show", SERVICE, "--property", property_name, "--value"],
        text=True, timeout=10,
    ).strip()


def current_address():
    # 限定当前运行实例，防止从历史日志误取已经失效的旧地址。
    if systemctl_value("ActiveState") != "active":
        raise RuntimeError("Cloudflare隧道尚未运行")
    invocation = systemctl_value("InvocationID")
    if not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise RuntimeError("无法确认隧道当前运行实例")
    logs = subprocess.check_output(
        ["journalctl", "-u", SERVICE, "_SYSTEMD_INVOCATION_ID=" + invocation,
         "--no-pager", "-o", "cat"], text=True, timeout=15,
    )
    addresses = re.findall(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com\b", logs)
    if not addresses:
        raise RuntimeError("当前隧道实例的日志中没有临时地址")
    return addresses[-1], invocation


def refresh():
    url, invocation = current_address()
    # 服务器直连探测，保留系统TLS证书验证；不使用代理或禁用HTTPS校验。
    opener = build_opener(ProxyHandler({}))
    with opener.open(url + "/", timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("临时网址主页不可用")
    with opener.open(url + "/api/health", timeout=20) as response:
        health = json.load(response)
    if health.get("status") != "ready" or not health.get("database") or not health.get("vector"):
        raise RuntimeError("网站数据库或向量服务尚未就绪")
    with opener.open("http://127.0.0.1:20241/ready", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("隧道连接尚未就绪")
    if systemctl_value("InvocationID") != invocation:
        raise RuntimeError("核验期间隧道已重建，请重新读取地址")
    path = ROOT / "data" / "cloudflare-tunnel-status.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    now = datetime.now(timezone.utc)
    result = {"url": url, "status": "reachable", "checked_at": now.isoformat(),
              "invocation_id": invocation, "phases": ["homepage", "https_health", "tunnel_ready"],
              "health": health, "previous_url": previous.get("url")}
    # 保留部署背景信息，旧网址的问答/登录测试结果不标记为新网址已验证。
    for key in ("public_http_disabled", "domains_paused", "cloudflared_version",
                "autostart_enabled", "document_import"):
        if key in previous:
            result[key] = previous[key]
    if path.exists():
        shutil.copy2(path, path.with_name("cloudflare-tunnel-status.before-" + now.strftime("%Y%m%dT%H%M%S%fZ") + ".json"))
    temporary = None
    try:
        # 原子替换避免读到半份JSON；保留原文件的运行用户，权限限制为600。
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".cloudflare-status-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        if path.exists():
            stat = path.stat()
            os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    refresh()
