# -*- coding: utf-8 -*-
"""auth 蓝图路由：登录 / 注册 / 登出。"""
from urllib.parse import urlparse

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import bp
from app.auth.forms import LoginForm, RegisterForm
from app.extensions import db
from app.models import Role, User

DEFAULT_USER_ROLE_ID = 2  # roles 表中 user 的默认 id（init_db 创建顺序为 admin=1, user=2）


def _is_safe_next(target: str) -> bool:
    """next 参数必须是站内相对路径，防止开放重定向。"""
    if not target:
        return False
    ref = urlparse(target)
    return not ref.netloc and not ref.scheme


@bp.route("/login", methods=["GET", "POST"])
def login():
    # 已登录用户直接进入仪表盘
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.execute(
            db.select(User).where(User.username == form.username.data.strip())
        ).scalar_one_or_none()
        if user is None or not user.check_password(form.password.data):
            flash("用户名或密码错误。", "danger")
        elif not user.is_active:
            flash("该账号已被禁用。", "danger")
        else:
            login_user(user, remember=form.remember.data)
            flash("登录成功，欢迎回来！", "success")
            next_url = request.args.get("next")
            if next_url and _is_safe_next(next_url):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        # 唯一性校验（重复时 flash 中文错误）
        if (
            db.session.execute(db.select(User).where(User.username == username))
            .scalar_one_or_none()
            is not None
        ):
            flash("该用户名已被注册。", "danger")
        elif (
            db.session.execute(db.select(User).where(User.email == email))
            .scalar_one_or_none()
            is not None
        ):
            flash("该邮箱已被注册。", "danger")
        else:
            # 默认角色 user
            role = db.session.execute(
                db.select(Role).where(Role.name == "user")
            ).scalar_one_or_none()
            user = User(
                username=username,
                email=email,
                role_id=role.id if role else DEFAULT_USER_ROLE_ID,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("注册成功，欢迎加入！", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("您已退出登录。", "info")
    return redirect(url_for("main.index"))
