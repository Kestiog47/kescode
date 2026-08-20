/* 后台管理系统前端脚本 */
document.addEventListener('DOMContentLoaded', function () {
    // 读取页面中的 CSRF token
    const meta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = meta ? meta.getAttribute('content') : '';

    /**
     * 全局 fetch 封装：自动携带 X-CSRFToken 请求头。
     * 用法：apiFetch('/api/posts', { method: 'POST', body: { title: 'x' } })
     * 传入对象 body 时自动序列化为 JSON 并设置 Content-Type。
     */
    window.apiFetch = function (url, options) {
        options = options || {};
        options.headers = Object.assign({}, options.headers);
        if (csrfToken) {
            options.headers['X-CSRFToken'] = csrfToken;
        }
        if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }
        return fetch(url, options);
    };
});
