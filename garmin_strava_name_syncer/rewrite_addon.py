import os
from urllib.parse import quote

from mitmproxy import http

REWRITE_DOMAINS = {"connectapi.garmin.com"}

PROXY_SERVER = os.getenv("PROXY_SERVER")
if not PROXY_SERVER:
    print("❌ PROXY_SERVER environment variable is not set.")
    print("   Please set it before running, e.g.:")
    print('   export PROXY_SERVER="https://your-proxy-server.example.com"')
    print("   Or source env.sh to load all required environment variables.")
    raise SystemExit(1)


class RewriteAddon:
    def request(self, flow: http.HTTPFlow):
        host = flow.request.host
        if host not in REWRITE_DOMAINS:
            return

        original_url = flow.request.pretty_url
        encoded_url = quote(original_url, safe="")
        new_url = f"{PROXY_SERVER}/api?{encoded_url}"

        flow.request.url = new_url
        print(f"[Rewrite] {original_url}")
        print(f"       -> {new_url}")


addons = [RewriteAddon()]
