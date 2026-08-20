# -*- coding: utf-8 -*-
"""数据库模型：Role / User / Post（SQLAlchemy 2.0 风格，Mapped/mapped_column）。

注意：查询一律使用 db.session.execute(db.select(...)) 或 db.session.get(Model, id)，
不使用已废弃的 Model.query。
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def _now():
    """返回带时区的当前时间（SQLite 存储为 UTC）。"""
    return datetime.now(timezone.utc)


class Role(db.Model):
    """角色：admin / user。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="role")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Role {self.name}>"


class User(UserMixin, db.Model):
    """用户。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id"), nullable=False, default=2
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    role: Mapped["Role"] = relationship(back_populates="users", lazy="joined")
    posts: Mapped[list["Post"]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        """设置密码（Werkzeug 默认 scrypt 哈希）。"""
        from werkzeug.security import generate_password_hash

        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """校验密码。"""
        from werkzeug.security import check_password_hash

        return check_password_hash(self.password_hash, password)

    def has_role(self, name: str) -> bool:
        """判断是否拥有指定角色。"""
        return self.role is not None and self.role.name == name

    def to_dict(self) -> dict:
        """序列化为字典（不含 password_hash，含角色名）。"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.name if self.role else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"


class Post(db.Model):
    """帖子。"""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    author: Mapped["User"] = relationship(back_populates="posts", lazy="joined")

    def to_dict(self) -> dict:
        """序列化为字典（含作者用户名）。"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "author_id": self.author_id,
            "author": self.author.username if self.author else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Post {self.title}>"
