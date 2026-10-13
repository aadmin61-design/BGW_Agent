"""仅预览web目录，避免静态服务器暴露.env和项目源文件。"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).resolve().parents[1] / "web"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/assets/"):
            self.path = path.removeprefix("/assets")
        super().do_GET()


if __name__ == "__main__":
    print("界面演示：http://127.0.0.1:8001/?demo=1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8001), Handler).serve_forever()
