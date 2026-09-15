# -*- coding: utf-8 -*-
"""EB 投研 Agent 平台 —— 一键启动。

    python main.py                 # 启动并自动开浏览器
    python main.py --port 9000     # 换端口
    python main.py --no-browser    # 不开浏览器（远程/排查用）
"""
import argparse
import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core import config            # noqa: E402
from app.web import routes, server     # noqa: E402

BANNER = """
+--------------------------------------------------------------+
|   EB 投研 Agent 平台                                          |
|   数据(Data) / 公告(Anno) / 舆情(Wechat)  ·  商汤 SenseNova 驱动  |
+--------------------------------------------------------------+
"""


def main():
    ap = argparse.ArgumentParser(description="EB 投研 Agent 平台")
    ap.add_argument("--host", default=None, help="监听地址，默认 127.0.0.1")
    ap.add_argument("--port", type=int, default=None, help="端口，默认 8765")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    c = config.load()
    url = ""

    def on_ready(u):
        nonlocal url
        url = u
        print(BANNER)
        print("  服务已启动： %s" % u)
        print("  平台目录：   %s" % config.PLATFORM_ROOT)
        print("  配置文件：   %s" % config.CONFIG_PATH)
        print("  Data 工作区：%s" % c["workspace"]["data"])
        print("  Anno 工作区：%s" % c["workspace"]["anno"])
        print("  Wechat 工作区：%s" % c["workspace"]["wechat"])
        print("")
        print("  按 Ctrl+C 停止服务")
        print("-" * 64)
        if not args.no_browser and c["server"].get("open_browser", True):
            threading.Timer(0.8, lambda: webbrowser.open(u)).start()

    server.serve_forever(routes.ROUTES, host=args.host, port=args.port,
                         on_ready=on_ready, quiet=False)


if __name__ == "__main__":
    try:
        main()
    except OSError as e:
        print("启动失败：%s" % e)
        print("多半是端口被占用，换一个：python main.py --port 9000")
        sys.exit(1)
