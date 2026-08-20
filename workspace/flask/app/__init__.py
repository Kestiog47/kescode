# -*- coding: utf-8 -*-
"""应用工厂 create_app。

职责：加载配置、初始化扩展、注册蓝图、注册错误处理器、注入 Jinja 全局变量。
"""
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for

from config import get_config


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    # 1. 初始化扩展
    from app.extensions import csrf, db, jwt, login_manager, migrate

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)

    # 2. 在应用上下文中导入模型，确保表元数据注册
    with app.app_context():
        from app import models  # noqa: F401

    # 3. 注册蓝图
    from app.admin import bp as admin_bp
    from app.api import bp as api_bp
    from app.auth import bp as auth_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # 4. 注册 JWT 统一错误处理（API JSON 错误格式）与数据库异常处理
    from app.api import errors as api_errors  # noqa: F401

    api_errors.register_error_handlers(app)

    # 5. user_loader：根据 session 中的用户 id 加载用户
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # 6. 未登录处理：API 请求返回 JSON 401，页面请求 flash + 跳转登录
    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api"):
            return (
                jsonify({"error": {"code": 401, "message": "未认证，请先登录。"}}),
                401,
            )
        from flask import flash

        flash(login_manager.login_message or "请先登录以访问该页面。", "warning")
        return redirect(url_for("auth.login", next=request.path))

    # 7. 全局错误处理器
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api"):
            return jsonify({"error": {"code": 404, "message": "资源不存在"}}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # 8. Jinja 全局变量
    app.jinja_env.globals["current_year"] = datetime.now().year

    return app
