# -*- coding: utf-8 -*-
"""表单：登录 / 注册 / 管理员创建用户。"""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    """登录表单。"""

    username = StringField("用户名", validators=[DataRequired(message="请输入用户名")])
    password = PasswordField("密码", validators=[DataRequired(message="请输入密码")])
    remember = BooleanField("记住我")
    submit = SubmitField("登录")


class RegisterForm(FlaskForm):
    """用户自助注册表单（默认角色 user）。"""

    username = StringField(
        "用户名",
        validators=[
            DataRequired(message="请输入用户名"),
            Length(min=3, max=80, message="用户名长度需在 3-80 之间"),
        ],
    )
    email = StringField(
        "邮箱",
        validators=[DataRequired(message="请输入邮箱"), Email(message="邮箱格式不正确")],
    )
    password = PasswordField(
        "密码",
        validators=[
            DataRequired(message="请输入密码"),
            Length(min=6, max=128, message="密码长度至少 6 位"),
        ],
    )
    confirm_password = PasswordField(
        "确认密码",
        validators=[
            DataRequired(message="请再次输入密码"),
            EqualTo("password", message="两次输入的密码不一致"),
        ],
    )
    submit = SubmitField("注册")


class AdminCreateUserForm(FlaskForm):
    """管理员创建用户表单（可指定角色）。"""

    username = StringField(
        "用户名",
        validators=[
            DataRequired(message="请输入用户名"),
            Length(min=3, max=80, message="用户名长度需在 3-80 之间"),
        ],
    )
    email = StringField(
        "邮箱",
        validators=[DataRequired(message="请输入邮箱"), Email(message="邮箱格式不正确")],
    )
    password = PasswordField(
        "密码",
        validators=[
            DataRequired(message="请输入密码"),
            Length(min=6, max=128, message="密码长度至少 6 位"),
        ],
    )
    # role 为下拉选择，choices 在路由中动态填充
    role = SelectField("角色", coerce=int, validators=[DataRequired(message="请选择角色")])
    submit = SubmitField("创建用户")
