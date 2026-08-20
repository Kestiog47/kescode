# NOTEPAD - flask-admin-system

## 任务
搭建 Flask 后台管理系统（flask-admin-system）：用户认证、REST API、数据库模型、前端模板。

## 计划 Todo
- [x] 检查工作区（空目录，Windows，Python 3.14.6，pip 26.1.2）
- [ ] 安装依赖（Flask 3.1.*, Flask-SQLAlchemy 3.1.*, Flask-Login 0.6.*, Flask-WTF 1.3.*, Flask-JWT-Extended 4.7.*, Flask-Migrate 4.1.*, python-dotenv 1.2.*, email-validator）
- [ ] 根目录文件：requirements.txt, config.py, run.py, init_db.py, .env.example, README.md
- [ ] app 核心：__init__.py (create_app), extensions.py, models.py, decorators.py
- [ ] auth 蓝图（routes.py, forms.py）
- [ ] main 蓝图（routes.py）
- [ ] admin 蓝图（routes.py）
- [ ] api 蓝图（routes.py, errors.py）
- [ ] templates + static
- [ ] 验证：语法检查、init_db、启动服务、curl 测试

## 关键决策/注意事项
- Python 3.14 可能对部分包无 wheel，需关注安装情况
- 查询一律用 db.session.execute(db.select(...)) / db.session.get，不用 Model.query
- REST API 蓝图用 jwt.csrf exempt 豁免（只豁免 API 蓝图）
- JWT identity 必须为字符串：str(user.id)
- 密码 scrypt：generate_password_hash / check_password_hash（Werkzeug 默认）
