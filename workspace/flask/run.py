# -*- coding: utf-8 -*-
"""应用入口：python run.py 启动，默认端口 5000。"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug 由配置控制（DevelopmentConfig.DEBUG=True）
    app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False))
