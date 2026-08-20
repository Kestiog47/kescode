# -*- coding: utf-8 -*-
"""auth 蓝图：登录 / 注册 / 登出。"""
from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/auth")

from app.auth import routes  # noqa: E402,F401
