# -*- coding: utf-8 -*-
"""自定义装饰器。"""
from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(role_name: str):
    """要求当前用户拥有指定角色，否则返回 403。

    用法：@login_required + @role_required('admin')
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if not current_user.has_role(role_name):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
