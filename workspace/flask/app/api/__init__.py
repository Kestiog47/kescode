# -*- coding: utf-8 -*-
"""api 蓝图：REST API（JWT Bearer 认证）。"""
from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from app.api import routes  # noqa: E402,F401
