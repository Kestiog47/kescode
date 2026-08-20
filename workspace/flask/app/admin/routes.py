# -*- coding: utf-8 -*-
"""admin 蓝图路由：用户 / 帖子 / 创建用户（仅 admin 角色）。"""
from flask import flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.admin import bp
from app.auth.forms import AdminCreateUserForm
from app.decorators import role_required
from app.extensions import db
from app.models import Post, Role, User


@bp.route("/users")
@role_required("admin")
@login_required
def users():
    users = db.session.execute(db.select(User).order_by(User.id)).scalars().all()
    return render_template("admin/users.html", users=users)


@bp.route("/posts")
@role_required("admin")
@login_required
def posts():
    posts = (
        db.session.execute(db.select(Post).order_by(Post.created_at.desc()))
        .scalars()
        .all()
    )
    return render_template("admin/posts.html", posts=posts)


@bp.route("/register", methods=["GET", "POST"])
@role_required("admin")
@login_required
def register():
    form = AdminCreateUserForm()
    # 动态填充角色下拉选项
    roles = db.session.execute(db.select(Role).order_by(Role.id)).scalars().all()
    form.role.choices = [(r.id, r.name) for r in roles]

    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
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
            user = User(username=username, email=email, role_id=form.role.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash(f"用户 {username} 创建成功。", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/register.html", form=form)
