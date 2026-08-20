# -*- coding: utf-8 -*-
"""main 蓝图路由：首页 / 仪表盘。"""
from flask import render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.main import bp
from app.models import Post


@bp.route("/")
def index():
    return render_template("main/index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    # 当前用户发帖总数
    post_count = db.session.execute(
        db.select(db.func.count(Post.id)).where(Post.author_id == current_user.id)
    ).scalar_one()
    # 最近 5 篇帖子
    recent_posts = (
        db.session.execute(
            db.select(Post)
            .where(Post.author_id == current_user.id)
            .order_by(Post.created_at.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )
    return render_template(
        "main/dashboard.html", post_count=post_count, recent_posts=recent_posts
    )
