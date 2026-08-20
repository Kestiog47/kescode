# -*- coding: utf-8 -*-
"""main 蓝图：首页 / 仪表盘。"""
from flask import Blueprint

bp = Blueprint("main", __name__)

from app.main import routes  # noqa: E402,F401
