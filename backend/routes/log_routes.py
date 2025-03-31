from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.services.log_service import LogService
from functools import wraps
from flask_cors import CORS, cross_origin
import os
import json
from backend.services.log_service_registry import LogServiceRegistry
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

log_bp = Blueprint('log', __name__)

# 配置 CORS
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS').split(',')
CORS(log_bp, 
     supports_credentials=True,
     origins=ALLOWED_ORIGINS,
     allow_headers=['Content-Type', 'Authorization', 'Access-Control-Allow-Credentials'],
     expose_headers=['Set-Cookie', 'Session'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

@log_bp.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers.update({
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, Accept, X-Line-Signature',
            'Access-Control-Allow-Methods': 'GET, PUT, POST, DELETE, OPTIONS',
            'Access-Control-Max-Age': '600',
            'Access-Control-Expose-Headers': 'Content-Type, Authorization, Set-Cookie',
            'Vary': 'Origin'
        })
    return response

def get_admin_id():
    """获取管理员ID"""
    logger.debug("當前 session: %s", dict(session))
    logger.debug("Authorization 頭部: %s", request.headers.get('Authorization'))
    
    # 首先尝试从 Authorization header 获取
    auth_header = request.headers.get('Authorization')
    if auth_header:
        logger.debug("找到 Authorization 頭部: %s", auth_header)
        # 支持 Bearer token 格式
        if auth_header.startswith('Bearer '):
            try:
                admin_id = int(auth_header.split(' ')[1])
                logger.debug("從 Bearer token 獲取到 admin_id: %s", admin_id)
                # 将 admin_id 存入 session
                session['admin_id'] = admin_id
                return admin_id
            except (IndexError, ValueError) as e:
                logger.warning("Bearer token 格式無效: %s", str(e))
        # 直接支持纯数字格式
        else:
            try:
                admin_id = int(auth_header)
                logger.debug("從純數字 Authorization 獲取到 admin_id: %s", admin_id)
                session['admin_id'] = admin_id
                return admin_id
            except ValueError as e:
                logger.warning("Authorization 頭部不是有效的數字: %s", str(e))
            
    # 如果没有 Authorization header，尝试从 session 获取
    admin_id = session.get('admin_id')
    if admin_id:
        try:
            admin_id = int(admin_id)
            logger.debug("從 session 獲取到 admin_id: %s", admin_id)
            return admin_id
        except ValueError as e:
            logger.warning("Session 中的 admin_id 無效: %s", str(e))
    
    logger.warning("無法獲取 admin_id")        
    return None

def check_view_log_permission():
    """檢查管理員是否有查看日誌的權限"""
    try:
        admin_id = get_admin_id()
        logger.debug("Checking view log permission for admin_id: %s", admin_id)
        
        if not admin_id:
            logger.warning("No admin_id found in session or header")
            return False
        
        # 直接從會話中獲取權限信息
        permissions = session.get('permissions', {})
        is_active = True  # 假設管理員是活躍的，因為他們能夠登錄
        
        logger.debug("Admin %s permission check:", admin_id)
        logger.debug("- Has view_system_logs permission: %s", permissions.get('can_view_system_logs', False))
        
        # 檢查管理員是否有查看系統日誌的權限
        return permissions.get('can_view_system_logs', False)
    
    except Exception as e:
        logger.error("Permission check error: %s", str(e))
        return False

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 對於 OPTIONS 請求，直接返回成功，不進行權限檢查
        if request.method == 'OPTIONS':
            return '', 204
            
        if not check_view_log_permission():
            return jsonify({"status": "error", "message": "需要管理員權限"}), 401
        return f(*args, **kwargs)
    return decorated_function

@log_bp.route("/logs", methods=['POST', 'OPTIONS'])
@admin_required
def get_logs():
    """獲取日誌記錄"""
    try:
        # 獲取請求參數
        data = request.get_json()
        logger.debug("接收到的請求數據: %s", data)
        
        table_name = data.get('table_name')
        operation_type = data.get('operation_type')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        user_type = data.get('user_type')
        performed_by = data.get('performed_by')
        record_detail = data.get('record_detail')  # 新增：獲取操作對象搜索參數
        record_only_search = data.get('record_only_search', False)  # 獲取是否僅搜索操作對象的參數
        page = data.get('page', 1)
        per_page = data.get('per_page', 10)

        logger.debug("過濾條件: table_name=%s, operation_type=%s, start_date=%s, end_date=%s, user_type=%s, performed_by=%s, record_detail=%s, record_only_search=%s", 
                    table_name, operation_type, start_date, end_date, user_type, performed_by, record_detail, record_only_search)
        logger.debug("分頁: page=%s, per_page=%s", page, per_page)

        # 計算分頁偏移量
        offset = (page - 1) * per_page

        # 獲取數據庫連接
        with get_db_connection() as db_connection:
            # 創建日誌服務實例
            log_service = LogServiceRegistry.get_service(db_connection)
            logger.debug("使用的日誌服務: %s", log_service.__class__.__name__)
            
            # 獲取日誌記錄
            logs, total_count = log_service.get_logs(
                table_name=table_name,
                operation_type=operation_type,
                start_date=start_date,
                end_date=end_date,
                user_type=user_type,
                performed_by=performed_by,
                record_detail=record_detail,  # 傳入操作對象搜索參數
                record_only_search=record_only_search,  # 傳入是否僅搜索操作對象的參數
                limit=per_page,
                offset=offset
            )
            
            # 確保logs是列表
            logs = logs if isinstance(logs, list) else []
            
            logger.debug("獲取到的日誌記錄數量: %s, 總記錄數: %s", len(logs), total_count)
            
            # 計算總頁數，確保不為零
            total_pages = max(1, (total_count + per_page - 1) // per_page if total_count and total_count > 0 else 1)
            
            # 返回日誌記錄
            return jsonify({
                "status": "success",
                "data": logs,
                "total_count": total_count,
                "current_page": page,
                "total_pages": total_pages
            })

    except Exception as e:
        logger.error("返回日誌記錄時發生錯誤: %s", str(e))
        # 即使發生錯誤，也返回一個有效的響應
        return jsonify({
            "status": "error",
            "message": "獲取日誌記錄時發生錯誤",
            "data": [],
            "total_count": 0,
            "current_page": page,
            "total_pages": 1
        })

@log_bp.route("/record", methods=['POST', 'OPTIONS'])
def record_log():
    """记录操作日志的端点，不需要权限检查"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "缺少必要參數"}), 400
            
        required_fields = ['table_name', 'operation_type', 'record_id', 'performed_by', 'user_type']
        for field in required_fields:
            if field not in data:
                return jsonify({"status": "error", "message": f"缺少參數: {field}"}), 400
        
        logger.debug("记录日志操作: %s - %s - ID: %s", data['operation_type'], data['table_name'], data['record_id'])
        
        with get_db_connection() as conn:
            log_service = LogService(conn)
            success = log_service.log_operation(
                table_name=data['table_name'],
                operation_type=data['operation_type'],
                record_id=data['record_id'],
                old_data=data.get('old_data'),
                new_data=data.get('new_data'),
                performed_by=data['performed_by'],
                user_type=data['user_type']
            )
            
            if success:
                logger.info("日志记录成功: %s - %s - ID: %s", data['operation_type'], data['table_name'], data['record_id'])
                return jsonify({"status": "success", "message": "日誌記錄成功"})
            else:
                logger.error("日志记录失败: %s - %s - ID: %s", data['operation_type'], data['table_name'], data['record_id'])
                return jsonify({"status": "error", "message": "日誌記錄失敗"}), 500
                
    except Exception as e:
        logger.error("记录日志时发生错误: %s", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@log_bp.route("/logs/stats", methods=['POST', 'OPTIONS'])
@admin_required
def get_log_stats():
    """获取日志统计信息"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 获取各类操作的数量统计
            cursor.execute("""
                SELECT operation_type, COUNT(*) 
                FROM logs 
                GROUP BY operation_type
            """)
            operation_stats = dict(cursor.fetchall())
            
            # 获取最近一周每天的日志数量
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) 
                FROM logs 
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
            daily_stats = dict(cursor.fetchall())
            
            # 获取各表的操作数量
            cursor.execute("""
                SELECT table_name, COUNT(*) 
                FROM logs 
                GROUP BY table_name
            """)
            table_stats = dict(cursor.fetchall())
            
            return jsonify({
                "status": "success",
                "data": {
                    "operation_stats": operation_stats,
                    "daily_stats": daily_stats,
                    "table_stats": table_stats
                }
            })
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 