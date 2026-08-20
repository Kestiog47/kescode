# -*- coding: utf-8 -*-
"""扩展统一实例化：db / migrate / login_manager / jwt / csrf。

这些扩展对象不绑定任何具体应用，在 create_app 中通过 init_app 注册。
"""
from flask_jwt_extended import JWTManager
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
jwt = JWTManager()
csrf = CSRFProtect()

# 未登录访问受保护页面时跳转到登录页
login_manager.login_view = "auth.login"
login_manager.login_message = "请先登录以访问该页面。"
login_manager.login_message_category = "warning"
