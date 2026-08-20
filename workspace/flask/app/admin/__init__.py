# -*- coding: utf-8 -*-
"""admin 蓝图：后台管理（仅 admin 角色）。"""
from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from app.admin import routes  # noqa: E402,F401
