# -*- coding: utf-8 -*-
"""REST API 蓝图路由。

所有 API 视图均使用 JWT Bearer 认证，并通过 @csrf.exempt 豁免 CSRF 校验
（API 使用 JWT 而非会话 Cookie，故无需 CSRF token）。
统一错误响应格式：{"error": {"code": <int>, "message": <str>}}
"""
from flask import jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)
from sqlalchemy.exc import IntegrityError

from app.api import bp
from app.extensions import csrf, db, jwt  # noqa: F401 (jwt 供 errors.py 使用，此处一并导入)
from app.models import Post, Role, User


def _api_error(code, message):
    """构造统一错误响应。"""
    return jsonify({"error": {"code": code, "message": message}}), code


def _role_claims(user):
    """构造 JWT 附加声明（角色信息）。"""
    return {"role": user.role.name if user.role else "user"}


def _is_admin():
    """判断当前 JWT 用户是否为 admin（优先取 claims，兜底查库）。"""
    if get_jwt().get("role") == "admin":
        return True
    user = db.session.get(User, int(get_jwt_identity()))
    return user is not None and user.has_role("admin")


@bp.route("/auth/register", methods=["POST"])
@csrf.exempt
def register():
    """注册新用户（默认角色 user）。"""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not username or not email or not password:
        return _api_error(400, "用户名、邮箱和密码不能为空。")

    if db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none():
        return _api_error(409, "用户名已被使用。")
    if db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none():
        return _api_error(409, "邮箱已被使用。")

    role = db.session.execute(db.select(Role).where(Role.name == "user")).scalar_one_or_none()
    user = User(username=username, email=email, role_id=role.id if role else 2)
    user.set_password(password)
    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _api_error(409, "用户名或邮箱已存在。")
    return jsonify({"message": "注册成功", "user": user.to_dict()}), 201


@bp.route("/auth/login", methods=["POST"])
@csrf.exempt
def login():
    """登录，返回 access_token / refresh_token 与用户信息。"""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return _api_error(400, "用户名和密码不能为空。")

    user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.check_password(password):
        return _api_error(401, "用户名或密码错误。")
    if not user.is_active:
        return _api_error(403, "账号已被禁用。")

    claims = _role_claims(user)
    access_token = create_access_token(identity=str(user.id), additional_claims=claims)
    refresh_token = create_refresh_token(identity=str(user.id))
    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user.to_dict(),
    })


@bp.route("/auth/refresh", methods=["POST"])
@csrf.exempt
@jwt_required(refresh=True)
def refresh():
    """使用 refresh token 换取新的 access token。"""
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return _api_error(401, "用户不存在。")
    access_token = create_access_token(
        identity=str(user.id), additional_claims=_role_claims(user)
    )
    return jsonify({"access_token": access_token})


@bp.route("/auth/me", methods=["GET"])
@csrf.exempt
@jwt_required()
def me():
    """返回当前登录用户信息。"""
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return _api_error(404, "用户不存在。")
    return jsonify({"user": user.to_dict()})


@bp.route("/posts", methods=["GET"])
@csrf.exempt
@jwt_required()
def list_posts():
    """帖子列表（按创建时间倒序）。"""
    posts = db.session.execute(
        db.select(Post).order_by(Post.created_at.desc())
    ).scalars().all()
    return jsonify({"posts": [p.to_dict() for p in posts], "total": len(posts)})


@bp.route("/posts", methods=["POST"])
@csrf.exempt
@jwt_required()
def create_post():
    """创建帖子。"""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return _api_error(400, "标题和内容不能为空。")
    post = Post(title=title, content=content, author_id=int(get_jwt_identity()))
    try:
        db.session.add(post)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _api_error(400, "创建帖子失败。")
    return jsonify({"message": "创建成功", "post": post.to_dict()}), 201


@bp.route("/posts/<int:post_id>", methods=["GET"])
@csrf.exempt
@jwt_required()
def get_post(post_id):
    """帖子详情。"""
    post = db.session.get(Post, post_id)
    if post is None:
        return _api_error(404, "帖子不存在。")
    return jsonify({"post": post.to_dict()})


@bp.route("/posts/<int:post_id>", methods=["PUT"])
@csrf.exempt
@jwt_required()
def update_post(post_id):
    """更新帖子（仅作者或 admin）。"""
    post = db.session.get(Post, post_id)
    if post is None:
        return _api_error(404, "帖子不存在。")
    current_user_id = int(get_jwt_identity())
    if post.author_id != current_user_id and not _is_admin():
        return _api_error(403, "没有权限修改该帖子。")
    data = request.get_json(silent=True) or {}
    if data.get("title"):
        post.title = data["title"].strip()
    if data.get("content"):
        post.content = data["content"].strip()
    db.session.commit()
    return jsonify({"message": "更新成功", "post": post.to_dict()})


@bp.route("/posts/<int:post_id>", methods=["DELETE"])
@csrf.exempt
@jwt_required()
def delete_post(post_id):
    """删除帖子（仅作者或 admin）。"""
    post = db.session.get(Post, post_id)
    if post is None:
        return _api_error(404, "帖子不存在。")
    current_user_id = int(get_jwt_identity())
    if post.author_id != current_user_id and not _is_admin():
        return _api_error(403, "没有权限删除该帖子。")
    db.session.delete(post)
    db.session.commit()
    return jsonify({"message": "删除成功"})
