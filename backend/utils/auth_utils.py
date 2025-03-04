from functools import wraps
from flask import session, jsonify, request
from backend.models.admin import Admin

def require_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            print(f"檢查權限: {permission}")
            print(f"當前 session: {dict(session)}")
            print(f"請求 headers: {dict(request.headers)}")
            
            # 首先从 session 中获取 admin_id
            admin_id = session.get('admin_id')
            
            # 如果 session 中没有，则尝试从 Authorization header 中获取
            auth_from_header = False
            if not admin_id:
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    admin_id = auth_header.split(' ')[1]
                    auth_from_header = True
                    print(f"從 Authorization header 獲取 admin_id: {admin_id}")
            
            if not admin_id:
                print("未找到 admin_id")
                return jsonify({
                    'status': 'error',
                    'message': '請先登入'
                }), 401

            # 如果使用Authorization头部或session中没有权限信息，则从数据库获取
            permissions = session.get('permissions')
            if auth_from_header or not permissions:
                admin_info = Admin.get_by_id(admin_id)
                if admin_info and admin_info.get('permissions'):
                    permissions = admin_info['permissions']
                    # 如果是通过session认证，将权限信息存入session
                    if not auth_from_header:
                        session['admin_id'] = admin_id
                        session['permissions'] = permissions
                    print(f"從數據庫獲取權限: {permissions}")
            
            if not permissions:
                print("未找到權限信息")
                return jsonify({
                    'status': 'error',
                    'message': '權限信息不存在'
                }), 401

            # 檢查是否有所需權限
            has_permission = permissions.get(permission, False)
            print(f"權限檢查結果: {has_permission}")
            
            if not has_permission:
                return jsonify({
                    'status': 'error',
                    'message': '權限不足'
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator 