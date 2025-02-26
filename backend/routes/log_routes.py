from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.services.log_service import LogService
from functools import wraps
from flask_cors import CORS
import os
import json

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
    # 首先尝试从 Authorization header 获取
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        try:
            admin_id = int(auth_header.split(' ')[1])
            # 将 admin_id 存入 session
            session['admin_id'] = admin_id
            return admin_id
        except (IndexError, ValueError):
            print("Invalid Authorization header format")
            
    # 如果没有 Authorization header，尝试从 session 获取
    admin_id = session.get('admin_id')
    if admin_id:
        try:
            return int(admin_id)
        except ValueError:
            print("Invalid admin_id in session")
            
    return None

def check_view_log_permission():
    """检查查看日志的权限"""
    # 如果是 OPTIONS 请求，直接返回 True
    if request.method == 'OPTIONS':
        return True
        
    admin_id = get_admin_id()
    print(f"Checking view log permission for admin_id: {admin_id}")
    print(f"Current session: {dict(session)}")
    print(f"Authorization header: {request.headers.get('Authorization')}")
    
    if not admin_id:
        print("No admin_id found in Authorization header or session")
        return False
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pl.can_view_system_logs, a.status, a.admin_name
                FROM administrators a
                JOIN permission_levels pl ON a.permission_level_id = pl.id
                WHERE a.id = %s
            """, (admin_id,))
            
            result = cursor.fetchone()
            if not result:
                print(f"No admin found with id: {admin_id}")
                return False
                
            has_permission = result[0]
            is_active = result[1] == 'active'
            admin_name = result[2]
            
            print(f"Admin {admin_name} permission check:")
            print(f"- Has view_system_logs permission: {has_permission}")
            print(f"- Is active: {is_active}")
            
            return has_permission and is_active
    except Exception as e:
        print(f"Error checking log permission: {str(e)}")
        return False

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not check_view_log_permission():
            return jsonify({"status": "error", "message": "需要管理員權限"}), 401
        return f(*args, **kwargs)
    return decorated_function

@log_bp.route("/logs", methods=['POST', 'OPTIONS'])
@admin_required
def get_logs():
    if request.method == 'OPTIONS':
        return '', 204
        
    print("Received request for logs")
    print(f"Headers: {dict(request.headers)}")
    print(f"Session: {dict(session)}")
    
    try:
        data = request.get_json()
        
        # 获取查询参数
        table_name = data.get('table_name')
        operation_type = data.get('operation_type')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        user_type = data.get('user_type')
        performed_by = data.get('performed_by')
        page = int(data.get('page', 1))
        per_page = int(data.get('per_page', 50))
        
        # 计算偏移量
        offset = (page - 1) * per_page
        
        with get_db_connection() as conn:
            log_service = LogService(conn)
            logs, total_count = log_service.get_logs(
                table_name=table_name,
                operation_type=operation_type,
                start_date=start_date,
                end_date=end_date,
                user_type=user_type,
                performed_by=performed_by,
                limit=per_page,
                offset=offset
            )
            
            # 构建基础查询
            base_query = """
                SELECT 
                    l.created_at,
                    l.user_type,
                    COALESCE(a.admin_name, c.company_name) as performer_name,
                    l.table_name,
                    CASE 
                        WHEN l.table_name = 'orders' THEN o.order_number
                        WHEN l.table_name = 'products' THEN p.name
                        WHEN l.table_name = 'customers' THEN cust.company_name
                        WHEN l.table_name = 'administrators' THEN adm.admin_name
                        ELSE l.record_id::text
                    END as record_detail,
                    l.operation_type,
                    l.operation_detail::text as operation_detail,
                    l.id,
                    l.performed_by
                FROM logs l
                LEFT JOIN administrators a ON l.performed_by = a.id AND l.user_type = '管理員'
                LEFT JOIN customers c ON l.performed_by = c.id AND l.user_type = '客戶'
                LEFT JOIN orders o ON l.table_name = 'orders' AND l.record_id = o.id
                LEFT JOIN products p ON l.table_name = 'products' AND l.record_id = p.id
                LEFT JOIN customers cust ON l.table_name = 'customers' AND l.record_id = cust.id
                LEFT JOIN administrators adm ON l.table_name = 'administrators' AND l.record_id = adm.id
            """
            
            conditions = []
            params = []
            
            if table_name:
                conditions.append("l.table_name = %s")
                params.append(table_name)
            
            if operation_type:
                conditions.append("l.operation_type = %s")
                params.append(operation_type)
                
            if start_date:
                conditions.append("l.created_at >= %s")
                params.append(start_date)
                
            if end_date:
                conditions.append("l.created_at <= %s")
                params.append(end_date)
                
            if user_type:
                conditions.append("l.user_type = %s")
                params.append(user_type)
                
            if performed_by:
                conditions.append("l.performed_by = %s")
                params.append(performed_by)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 获取总记录数
            count_query = f"""
                SELECT COUNT(*) 
                FROM logs l 
                WHERE {where_clause}
            """
            cursor = conn.cursor()
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]
            
            # 获取日志记录
            query = f"""
                {base_query}
                WHERE {where_clause}
                ORDER BY l.created_at DESC
                LIMIT %s OFFSET %s
            """
            
            cursor.execute(query, params + [per_page, offset])
            logs = cursor.fetchall()
            
            # 转换日志记录为字典列表
            log_list = []
            for log in logs:
                try:
                    operation_detail = log[6]
                    if operation_detail and isinstance(operation_detail, str):
                        try:
                            operation_detail = json.loads(operation_detail)
                        except json.JSONDecodeError:
                            pass
                except Exception as e:
                    print(f"Error processing operation_detail: {e}")
                    operation_detail = log[6]

                log_dict = {
                    'created_at': log[0].strftime('%Y-%m-%d %H:%M:%S'),
                    'user_type': log[1],
                    'performer_name': log[2],
                    'table_name': log[3],
                    'record_detail': log[4],
                    'operation_type': log[5],
                    'operation_detail': operation_detail,
                    'id': log[7],
                    'performed_by': log[8]
                }
                log_list.append(log_dict)
            
            return jsonify({
                "status": "success",
                "data": {
                    "logs": log_list,
                    "total": total_count,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": (total_count + per_page - 1) // per_page
                }
            })
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

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
        
        print(f"记录日志操作: {data['operation_type']} - {data['table_name']} - ID: {data['record_id']}")
        
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
                print(f"日志记录成功: {data['operation_type']} - {data['table_name']} - ID: {data['record_id']}")
                return jsonify({"status": "success", "message": "日誌記錄成功"})
            else:
                print(f"日志记录失败: {data['operation_type']} - {data['table_name']} - ID: {data['record_id']}")
                return jsonify({"status": "error", "message": "日誌記錄失敗"}), 500
                
    except Exception as e:
        print(f"记录日志时发生错误: {str(e)}")
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