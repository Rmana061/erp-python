from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.models.admin import Admin
from backend.utils.auth_utils import require_permission
from hash_password import verify_password, hash_password
import psycopg2.extras

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/list', methods=['POST'])
def get_admin_list():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, admin_account, admin_name, staff_no,
                       permission_level_id, status, created_at, updated_at 
                FROM administrators 
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            admins = []
            for row in cursor.fetchall():
                admin_dict = dict(zip(columns, row))
                # 格式化日期
                if admin_dict.get('created_at'):
                    admin_dict['created_at'] = admin_dict['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if admin_dict.get('updated_at'):
                    admin_dict['updated_at'] = admin_dict['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                admins.append(admin_dict)
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": admins
            })
    except Exception as e:
        print(f"Error in get_admin_list: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"獲取管理員列表失敗: {str(e)}"
        }), 500

@admin_bp.route('/admin/add', methods=['POST'])
@require_permission('can_add_personnel')
def add_admin():
    try:
        data = request.json
        print("接收到的数据:", data)
        
        # 获取当前管理员ID
        admin_id = session.get('admin_id')
        if not admin_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                admin_id = auth_header.split(' ')[1]
        
        if not admin_id:
            return jsonify({
                "status": "error",
                "message": "未登入或登入已過期"
            }), 401
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查必要欄位
            required_fields = ['admin_account', 'admin_password', 'admin_name', 
                             'staff_no', 'permission_level_id']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({
                        "status": "error",
                        "message": f"缺少必要欄位: {field}"
                    }), 400

            # 檢查帳號是否已存在
            cursor.execute("""
                SELECT id FROM administrators 
                WHERE admin_account = %s AND status = 'active'
            """, (data['admin_account'],))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "管理員帳號已存在"
                }), 400

            # 檢查工號是否已存在
            cursor.execute("""
                SELECT id FROM administrators 
                WHERE staff_no = %s AND status = 'active'
            """, (data['staff_no'],))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "工號已存在"
                }), 400
            
            # 密碼加密
            hashed_password = hash_password(data['admin_password'])
            
            # 插入新管理員
            cursor.execute("""
                INSERT INTO administrators (
                    admin_account, admin_password, admin_name, staff_no,
                    permission_level_id, status, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'active', NOW(), NOW()
                ) RETURNING id
            """, (
                data['admin_account'], hashed_password, data['admin_name'],
                data['staff_no'], data['permission_level_id']
            ))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            
            # 获取权限级别名称
            cursor.execute("""
                SELECT level_name FROM permission_levels
                WHERE id = %s
            """, (data['permission_level_id'],))
            permission_level_result = cursor.fetchone()
            permission_level = permission_level_result[0] if permission_level_result else "未知權限"
            
            # 添加日志记录
            from backend.services.log_service import LogService
            log_service = LogService(conn)
            
            # 准备日志数据，不包含密码
            new_admin_data = {
                'id': new_id,
                'admin_account': data['admin_account'],
                'admin_name': data['admin_name'],
                'staff_no': data['staff_no'],
                'permission_level_id': data['permission_level_id'],
                'permission_level': permission_level,
                'status': 'active'
            }
            
            log_service.log_operation(
                table_name='administrators',
                operation_type='新增',
                record_id=new_id,
                old_data=None,
                new_data=new_admin_data,
                performed_by=int(admin_id),
                user_type='管理員'
            )
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "message": "管理員新增成功",
                "id": new_id
            })
            
    except Exception as e:
        print(f"Error in add_admin: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"新增管理員失敗: {str(e)}"
        }), 500

@admin_bp.route('/admin/update', methods=['POST'])
@require_permission('can_add_personnel')
def update_admin():
    try:
        data = request.get_json()
        admin_id = data.get('id')
        admin_account = data.get('admin_account')
        admin_password = data.get('admin_password')
        admin_name = data.get('admin_name')
        staff_no = data.get('staff_no')
        permission_level_id = data.get('permission_level_id')
        
        if not all([admin_id, admin_account, admin_name, staff_no, permission_level_id]):
            return jsonify({
                "status": "error",
                "message": "缺少必要的欄位"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 获取当前管理员ID（操作者）
            current_admin_id = session.get('admin_id')
            if not current_admin_id:
                auth_header = request.headers.get('Authorization')
                if auth_header and auth_header.startswith('Bearer '):
                    current_admin_id = auth_header.split(' ')[1]
            
            if not current_admin_id:
                return jsonify({
                    "status": "error",
                    "message": "未登入或登入已過期"
                }), 401
                
            # 先获取更新前的管理员数据（用于日志记录）
            cursor.execute("""
                SELECT a.id, a.admin_account, a.admin_name, a.staff_no, 
                       a.permission_level_id, p.level_name
                FROM administrators a
                LEFT JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.id = %s AND a.status = 'active'
            """, (admin_id,))
            
            old_admin_result = cursor.fetchone()
            if not old_admin_result:
                return jsonify({
                    "status": "error",
                    "message": "找不到要更新的管理員"
                }), 404
                
            old_admin_data = {
                'id': old_admin_result[0],
                'admin_account': old_admin_result[1],
                'admin_name': old_admin_result[2],
                'staff_no': old_admin_result[3],
                'permission_level_id': old_admin_result[4],
                'permission_level': old_admin_result[5] if old_admin_result[5] else "未知權限"
            }

            # 检查账号是否与其他管理员重复
            cursor.execute("""
                SELECT id FROM administrators 
                WHERE admin_account = %s AND id != %s AND status = 'active'
            """, (admin_account, admin_id))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "管理員帳號已存在"
                }), 400

            # 检查工号是否与其他管理员重复
            cursor.execute("""
                SELECT id FROM administrators 
                WHERE staff_no = %s AND id != %s AND status = 'active'
            """, (staff_no, admin_id))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "工號已存在"
                }), 400

            update_fields = [
                "admin_account = %s",
                "admin_name = %s",
                "staff_no = %s",
                "permission_level_id = %s",
                "updated_at = CURRENT_TIMESTAMP"
            ]
            params = [admin_account, admin_name, staff_no, permission_level_id]

            if admin_password:
                update_fields.append("admin_password = %s")
                params.append(hash_password(admin_password))

            params.append(admin_id)  # for WHERE clause

            query = f"""
                UPDATE administrators 
                SET {", ".join(update_fields)}
                WHERE id = %s
                RETURNING id
            """

            cursor.execute(query, params)
            updated = cursor.fetchone()
            
            # 获取更新后的权限级别名称
            cursor.execute("""
                SELECT level_name FROM permission_levels
                WHERE id = %s
            """, (permission_level_id,))
            permission_level_result = cursor.fetchone()
            permission_level = permission_level_result[0] if permission_level_result else "未知權限"
            
            # 准备新的管理员数据（用于日志记录）
            new_admin_data = {
                'id': admin_id,
                'admin_account': admin_account,
                'admin_name': admin_name,
                'staff_no': staff_no,
                'permission_level_id': permission_level_id,
                'permission_level': permission_level
            }
            
            # 如果更新了密码，在日志数据中添加标记
            if admin_password:
                new_admin_data['admin_password'] = 'updated'
            
            # 记录更新操作日志
            from backend.services.log_service import LogService
            log_service = LogService(conn)
            
            log_service.log_operation(
                table_name='administrators',
                operation_type='修改',
                record_id=int(admin_id),
                old_data=old_admin_data,
                new_data=new_admin_data,
                performed_by=int(current_admin_id),
                user_type='管理員'
            )
            
            conn.commit()
            cursor.close()
            
            return jsonify({
                "status": "success",
                "message": "管理員資料更新成功"
            })

    except Exception as e:
        print(f"Error in update_admin: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"更新管理員資料失敗: {str(e)}"
        }), 500

@admin_bp.route('/admin/delete', methods=['POST'])
@require_permission('can_add_personnel')
def delete_admin():
    try:
        data = request.json
        if 'id' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少管理員ID"
            }), 400

        # 检查用户权限（即使已有装饰器，再次显式检查）
        print("手动检查权限...")
        # 获取当前管理员ID
        current_admin_id = session.get('admin_id')
        if not current_admin_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                current_admin_id = auth_header.split(' ')[1]
        
        if not current_admin_id:
            return jsonify({
                "status": "error",
                "message": "未登入或登入已過期"
            }), 401
        
        # 获取管理员权限
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT p.can_add_personnel
                FROM administrators a
                JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.id = %s AND a.status = 'active'
            """, (current_admin_id,))
            
            permission_result = cursor.fetchone()
            if not permission_result or not permission_result[0]:
                print(f"权限检查失败: admin_id={current_admin_id}, 权限查询结果:", permission_result)
                return jsonify({
                    "status": "error",
                    "message": "您沒有足夠的權限執行此操作"
                }), 403
            
            print(f"权限检查成功: admin_id={current_admin_id}, can_add_personnel=True")
            
            # 先获取要删除的管理员数据（用于日志记录）
            cursor.execute("""
                SELECT a.id, a.admin_account, a.admin_name, a.staff_no, 
                       a.permission_level_id, p.level_name
                FROM administrators a
                LEFT JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.id = %s AND a.status = 'active'
            """, (data['id'],))
            
            admin_result = cursor.fetchone()
            if not admin_result:
                return jsonify({
                    "status": "error",
                    "message": "管理員不存在"
                }), 404
                
            admin_data = {
                'id': admin_result[0],
                'admin_account': admin_result[1],
                'admin_name': admin_result[2],
                'staff_no': admin_result[3],
                'permission_level_id': admin_result[4],
                'permission_level': admin_result[5] if admin_result[5] else "未知權限"
            }

            # 軟刪除管理員
            cursor.execute("""
                UPDATE administrators 
                SET status = 'inactive', updated_at = NOW()
                WHERE id = %s
            """, (data['id'],))
            
            # 记录删除操作日志
            from backend.services.log_service import LogService
            log_service = LogService(conn)
            
            log_service.log_operation(
                table_name='administrators',
                operation_type='刪除',
                record_id=int(data['id']),
                old_data=admin_data,
                new_data=None,
                performed_by=int(current_admin_id),
                user_type='管理員'
            )
            
            conn.commit()
            cursor.close()
            
            return jsonify({
                "status": "success",
                "message": "管理員刪除成功"
            })
            
    except Exception as e:
        print(f"Error in delete_admin: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"刪除管理員失敗: {str(e)}"
        }), 500

@admin_bp.route('/admin/info', methods=['POST'])
def get_admin_info():
    try:
        print("開始獲取管理員信息...")
        print("當前 session:", dict(session))
        print("請求 headers:", dict(request.headers))
        
        # 获取请求中的特定管理员ID
        data = request.get_json()
        target_admin_id = data.get('admin_id')
        
        # 首先从 session 中获取当前登录的管理员ID
        current_admin_id = session.get('admin_id')
        
        # 如果 session 中没有，则尝试从 Authorization header 中获取
        if not current_admin_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                current_admin_id = auth_header.split(' ')[1]
                session['admin_id'] = current_admin_id
        
        print("當前管理員 ID:", current_admin_id)
        print("目標管理員 ID:", target_admin_id)
        
        if not current_admin_id:
            print("未找到當前管理員 ID")
            return jsonify({"status": "error", "message": "未登入或登入已過期"}), 401

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # 如果有指定要查询的管理员ID，就查询该ID的信息
            admin_id_to_query = target_admin_id if target_admin_id else current_admin_id
            
            cursor.execute("""
                SELECT a.*, p.*
                FROM administrators a
                JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.id = %s AND a.status = 'active'
            """, (admin_id_to_query,))
            
            admin = cursor.fetchone()
            cursor.close()
            
            if not admin:
                print("管理員不存在")
                return jsonify({"status": "error", "message": "管理員不存在"}), 404
            
            print("查詢到的管理員信息:", dict(admin))
            
            result = {
                "status": "success",
                "data": {
                    "id": admin['id'],
                    "admin_account": admin['admin_account'],
                    "admin_name": admin['admin_name'],
                    "staff_no": admin['staff_no'],
                    "permission_level_id": admin['permission_level_id'],
                    "permissions": {
                        "can_approve_orders": bool(admin['can_approve_orders']),
                        "can_edit_orders": bool(admin['can_edit_orders']),
                        "can_close_order_dates": bool(admin['can_close_order_dates']),
                        "can_add_customer": bool(admin['can_add_customer']),
                        "can_add_product": bool(admin['can_add_product']),
                        "can_add_personnel": bool(admin['can_add_personnel']),
                        "can_view_system_logs": bool(admin['can_view_system_logs']),
                        "can_decide_product_view": bool(admin['can_decide_product_view'])
                    }
                }
            }
            
            print("Response:", result)
            return jsonify(result)

    except Exception as e:
        print(f"Error in get_admin_info: {str(e)}")
        return jsonify({"status": "error", "message": "獲取管理員資訊失敗"}), 500

@admin_bp.route('/admin/check-permissions', methods=['POST'])
def check_permissions():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT * FROM permission_levels
                ORDER BY id ASC
            """)
            
            permissions = []
            for row in cursor.fetchall():
                permissions.append(dict(row))
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": permissions
            })
    except Exception as e:
        print(f"Error in check_permissions: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"檢查權限失敗: {str(e)}"
        }), 500 