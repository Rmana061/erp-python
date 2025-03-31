from functools import wraps
from flask import session, jsonify, request
from backend.models.admin import Admin
from backend.config.database import get_db_connection
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

def require_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            logger.debug("檢查權限: %s", permission)
            logger.debug("當前 session: %s", dict(session))
            logger.debug("請求 headers: %s", dict(request.headers))
            
            # 首先从 session 中获取 admin_id
            admin_id = session.get('admin_id')
            
            # 如果 session 中没有，则尝试从 Authorization header 中获取
            auth_from_header = False
            if not admin_id:
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    admin_id = auth_header.split(' ')[1]
                    auth_from_header = True
                    logger.debug("從 Authorization header 獲取 admin_id: %s", admin_id)
            
            if not admin_id:
                logger.warning("未找到 admin_id")
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
                    logger.debug("從數據庫獲取權限: %s", permissions)
            
            if not permissions:
                logger.warning("未找到權限信息")
                return jsonify({
                    'status': 'error',
                    'message': '權限信息不存在'
                }), 401

            # 檢查是否有所需權限
            has_permission = permissions.get(permission, False)
            logger.debug("權限檢查結果: %s", has_permission)
            
            if not has_permission:
                return jsonify({
                    'status': 'error',
                    'message': '權限不足'
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator 

def check_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            logger.debug("檢查權限: %s", permission)
            logger.debug("當前 session: %s", dict(session))
            logger.debug("請求 headers: %s", dict(request.headers))

            # 檢查是否有 admin_id
            admin_id = None

            # 從 session 中獲取
            if 'admin_id' in session:
                admin_id = session['admin_id']

            # 如果 session 中沒有，嘗試從 Authorization header 獲取
            if not admin_id and 'Authorization' in request.headers:
                try:
                    admin_id = int(request.headers['Authorization'])
                    logger.debug("從 Authorization header 獲取 admin_id: %s", admin_id)
                except (ValueError, TypeError):
                    pass

            if not admin_id:
                logger.warning("未找到 admin_id")
                return {'status': 'error', 'message': '未授權訪問'}, 401

            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT ap.permission
                        FROM admins a
                        LEFT JOIN admin_permissions ap ON a.id = ap.admin_id
                        WHERE a.id = %s AND a.status = 'active'
                    """, (admin_id,))
                    
                    permissions = [row['permission'] for row in cursor.fetchall()]
                    logger.debug("從數據庫獲取權限: %s", permissions)

                    if not permissions:
                        logger.warning("未找到權限信息")
                        return {'status': 'error', 'message': '未授權訪問'}, 401

                    # 檢查是否有所需權限
                    has_permission = permission in permissions

                    logger.debug("權限檢查結果: %s", has_permission)

                    if not has_permission:
                        return {'status': 'error', 'message': '權限不足'}, 403

                    return f(*args, **kwargs)

            except Exception as e:
                logger.error("權限檢查時發生錯誤: %s", str(e))
                return {'status': 'error', 'message': '權限檢查失敗'}, 500

        return decorated_function
    return decorator 