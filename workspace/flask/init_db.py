# -*- coding: utf-8 -*-
"""初始化数据库：创建所有表 + 幂等创建默认角色与管理员。

用法：
    python init_db.py

默认管理员：admin / admin123（email: admin@example.com，角色 admin）
"""
from app import create_app
from app.extensions import db
from app.models import Role, User

app = create_app()


def init_db():
    with app.app_context():
        # 1. 创建所有表（已存在则跳过）
        db.create_all()
        print("[OK] 数据库表创建完成")

        # 2. 幂等创建默认角色
        roles = {
            "admin": "系统管理员，拥有后台管理权限",
            "user": "普通用户",
        }
        created_roles = 0
        for name, desc in roles.items():
            role = db.session.execute(
                db.select(Role).where(Role.name == name)
            ).scalar_one_or_none()
            if role is None:
                db.session.add(Role(name=name, description=desc))
                created_roles += 1
                print(f"[OK] 创建角色: {name}")
            else:
                print(f"[SKIP] 角色已存在: {name}")
        db.session.flush()

        # 3. 幂等创建默认管理员
        admin_role = db.session.execute(
            db.select(Role).where(Role.name == "admin")
        ).scalar_one_or_none()
        admin = db.session.execute(
            db.select(User).where(User.username == "admin")
        ).scalar_one_or_none()
        if admin is None and admin_role is not None:
            admin = User(
                username="admin",
                email="admin@example.com",
                role_id=admin_role.id,
                is_active=True,
            )
            admin.set_password("admin123")
            db.session.add(admin)
            print("[OK] 创建默认管理员: admin / admin123")
        elif admin is not None:
            print("[SKIP] 管理员已存在: admin")

        db.session.commit()
        print("[OK] 初始化完成")


if __name__ == "__main__":
    init_db()
