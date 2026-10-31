"""书法知识图谱应用。用法：.venv/bin/python app/server.py [端口]，然后打开 http://localhost:8766"""
import json, os, re, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kg import KG, ROOT
from qa import QA

print("正在载入图谱……", flush=True)
kg = KG()
qa = QA(kg)
STATIC = os.path.join(ROOT, "app", "static")
READ_ONLY = re.compile(r"^\s*((#[^\n]*\n|PREFIX\s+\S+\s*<[^>]*>)\s*)*(SELECT|ASK)\b", re.I)


def api(path, q):
    get = lambda k, d="": q.get(k, [d])[0]
    domains = [d for d in get("domains").split(",") if d] or None
    if path == "/api/ask":
        return qa.answer(get("q"))
    if path == "/api/search":
        return {"results": kg.search(get("q"), get("type") or None, 40)}
    if path == "/api/entity":
        return kg.entity(get("id")) or {"error": "实体不存在"}
    if path == "/api/network":
        center = get("id") or None
        return kg.network(center, int(get("depth", "2")), domains)
    if path == "/api/path":
        return {"steps": kg.path(get("a"), get("b"), domains)}
    if path == "/api/analysis":
        return kg.analysis
    if path == "/api/stats":
        return kg.stats
    if path == "/api/sparql":
        query = get("q")
        if not READ_ONLY.match(query):  # 只开放只读查询
            return {"error": "只支持 SELECT 和 ASK 查询"}
        try:
            return {"rows": kg.sparql(query)[:500]}
        except Exception as e:
            return {"error": str(e)[:400]}
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith("/api/"):
            try:
                data = api(u.path, urllib.parse.parse_qs(u.query))
            except Exception as e:
                data, code = {"error": str(e)[:400]}, 500
            else:
                code = 200 if data is not None else 404
            return self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)
        name = "index.html" if u.path == "/" else os.path.basename(u.path)
        fp = os.path.join(STATIC, name)
        if not os.path.isfile(fp):
            return self._send(b"not found", "text/plain", 404)
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
        self._send(open(fp, "rb").read(), ctype)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print(f"已启动：http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
