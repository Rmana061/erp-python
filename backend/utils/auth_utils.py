from functools import wraps
from flask import session, jsonify
from backend.models.admin import Admin

def require_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            print(f"檢查權限: {permission}")
            print(f"當前 session: {dict(session)}")
            
            # 檢查是否已登入
            admin_id = session.get('admin_id')
            if not admin_id:
                print("未找到 admin_id")
                return jsonify({
                    'status': 'error',
                    'message': '請先登入'
                }), 401

            # 直接從 session 中獲取權限
            permissions = session.get('permissions', {})
            print(f"從 session 獲取的權限: {permissions}")
            
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