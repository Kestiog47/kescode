# Flask 后台管理系统

一个基于 Flask 3.x 的完整后台管理系统示例，包含用户认证（会话 + JWT）、角色权限、REST API、SQLAlchemy 数据库模型与 Bootstrap 5 前端模板。

## 功能特性

- 用户注册 / 登录 / 登出（Flask-Login 会话认证）
- 角色权限：`admin`（管理员）/ `user`（普通用户），仅 admin 可访问后台管理
- REST API：JWT 认证（access + refresh token），统一 JSON 错误格式
- 数据库模型：Role / User / Post（SQLAlchemy 2.0 风格，密码 scrypt 哈希，绝不存明文）
- 前端模板：Bootstrap 5（CDN）+ 少量自定义 CSS / JS（fetch 自动携带 CSRF token）

## 技术栈

| 组件 | 版本 |
| --- | --- |
| Flask | 3.1.3 |
| Flask-SQLAlchemy | 3.1.1 |
| Flask-Login | 0.6.3 |
| Flask-WTF | 1.3.0 |
| Flask-JWT-Extended | 4.7.4 |
| Flask-Migrate | 4.1.0 |
| python-dotenv | 1.2.3 |
| email-validator | 2.3.0 |

## 项目结构

```
run.py                      # 入口：python run.py 启动，端口 5000
config.py                   # 基于环境变量的配置类
requirements.txt
.env.example                # 环境变量示例（SECRET_KEY / DATABASE_URL / JWT_SECRET_KEY）
README.md
init_db.py                  # 创建表 + 幂等创建默认角色与管理员
app/
  __init__.py               # create_app 应用工厂
  extensions.py             # db / migrate / login_manager / jwt / csrf
  models.py                 # Role / User / Post
  decorators.py             # role_required
  auth/__init__.py          # 会话认证蓝图（/auth）
  auth/routes.py
  auth/forms.py             # LoginForm / RegisterForm
  main/__init__.py          # 前台页面蓝图（首页 / 仪表盘）
  main/routes.py
  admin/__init__.py         # 后台管理蓝图（/admin，仅 admin）
  admin/routes.py           # users / posts / register
  api/__init__.py           # REST API 蓝图（/api）
  api/routes.py
  api/errors.py             # JWT 回调 + 统一 JSON 错误处理
  templates/
    base.html
    auth/login.html
    auth/register.html
    main/index.html
    main/dashboard.html
    admin/users.html
    admin/posts.html
    admin/register.html
    errors/403.html
    errors/404.html
    errors/500.html
  static/
    css/style.css
    js/main.js
```

## 快速开始

1. （可选）创建虚拟环境：`python -m venv .venv`
2. 安装依赖：`python -m pip install -r requirements.txt`
3. 复制环境变量文件：`copy .env.example .env`
4. 初始化数据库：`python init_db.py`（自动创建表、默认角色与管理员）
5. 启动：`python run.py`，浏览器访问 <http://127.0.0.1:5000>

默认管理员账号：`admin` / `admin123`

## 页面路由

| 路径 | 说明 | 权限 |
| --- | --- | --- |
| `/` | 首页 | 公开 |
| `/auth/login` | 登录 | 公开 |
| `/auth/register` | 注册 | 公开 |
| `/auth/logout` | 登出 | 已登录 |
| `/dashboard` | 仪表盘 | 已登录 |
| `/admin/users` | 用户管理 | 仅 admin |
| `/admin/posts` | 帖子管理 | 仅 admin |
| `/admin/register` | 创建用户 | 仅 admin |

## REST API

统一响应格式（错误）：`{"error": {"code": 400, "message": "..."}}`

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | 无 | 注册（201，返回用户信息） |
| POST | `/api/auth/login` | 无 | 登录（返回 access_token / refresh_token / user） |
| POST | `/api/auth/refresh` | refresh token | 刷新 access token |
| GET | `/api/auth/me` | Bearer | 当前登录用户信息 |
| GET | `/api/posts` | Bearer | 帖子列表（按时间倒序） |
| POST | `/api/posts` | Bearer | 创建帖子（title / content 必填） |
| GET | `/api/posts/<id>` | Bearer | 帖子详情 |
| PUT | `/api/posts/<id>` | Bearer | 更新帖子（作者或 admin） |
| DELETE | `/api/posts/<id>` | Bearer | 删除帖子（作者或 admin） |

### curl 示例

```bash
# 1. 注册
curl -X POST http://127.0.0.1:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123", "email": "alice@example.com"}'

# 2. 登录，获取 token
curl -X POST http://127.0.0.1:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
# 响应中取出 access_token / refresh_token

# 3. 携带 Bearer token 访问帖子列表
curl http://127.0.0.1:5000/api/posts \
  -H "Authorization: Bearer <access_token>"

# 4. 使用 refresh token 刷新 access token
curl -X POST http://127.0.0.1:5000/api/auth/refresh \
  -H "Authorization: Bearer <refresh_token>"
```

> 提示：Windows cmd 下使用 curl 时注意引号转义——外层用双引号包裹，内部字段用单引号或 `\"` 转义。
