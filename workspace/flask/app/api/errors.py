# -*- coding: utf-8 -*-
"""REST API 统一错误处理。

- JWT 相关回调（unauthorized / invalid / expired）统一返回 JSON
- 未捕获异常：/api 路径返回 500 JSON，其余交由全局处理器
- 404 由 app/__init__.py 的全局 not_found 按路径分流，不再在此注册
"""
from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from app.extensions import db, jwt


def register_error_handlers(app):
    """注册 JWT 回调与 API 错误处理器（在 create_app 内调用）。"""

    @jwt.unauthorized_loader
    def unauthorized_callback(_reason):
        return jsonify({"error": {"code": 401, "message": "缺少或无效的认证令牌。"}}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify({"error": {"code": 422, "message": f"无效的令牌：{reason}"}}), 422

    @jwt.expired_token_loader
    def expired_token_callback(_header, _payload):
        return jsonify({"error": {"code": 401, "message": "令牌已过期，请重新登录。"}}), 401

    @app.errorhandler(Exception)
    def handle_error(e):
        # HTTPException 交给 Flask 默认处理（全局 403/404/500 模板处理器接管）
        if isinstance(e, HTTPException):
            return e
        db.session.rollback()
        app.logger.error("Unhandled error: %s", e)
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": 500, "message": "服务器内部错误"}}), 500
        raise e
