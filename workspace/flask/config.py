# -*- coding: utf-8 -*-
"""应用配置：基于环境变量的配置类（Development / Production / Testing）。

从项目根目录自动加载 .env 文件（python-dotenv），所有敏感配置优先读取环境变量。
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（config.py 所在目录）
BASE_DIR = Path(__file__).resolve().parent

# 自动加载 .env（若存在），已存在的环境变量不会被覆盖
load_dotenv(BASE_DIR / ".env")


class Config:
    """基础配置，所有环境共享的默认值。"""

    SECRET_KEY = os.environ.get(
        "SECRET_KEY", "dev-secret-change-me-please-replace-in-production-0123456789"
    )

    # 数据库：默认使用项目根目录下的 sqlite:///app.db（绝对路径）
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + str(BASE_DIR / "app.db").replace("\\", "/"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 会话 Cookie 安全设置
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # 生产环境必须通过环境变量显式开启 Secure
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Flask-WTF CSRF：令牌不设过期时间（开发环境方便调试）
    WTF_CSRF_TIME_LIMIT = None

    # Flask-JWT-Extended
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_TOKEN_LOCATION = ["headers"]

    # 通用
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """开发环境。"""

    DEBUG = True


class ProductionConfig(Config):
    """生产环境：强制安全 Cookie。"""

    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """测试环境：使用内存数据库。"""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


# 通过环境变量 FLASK_ENV 选择配置，默认 Development
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config_map.get(env, DevelopmentConfig)
