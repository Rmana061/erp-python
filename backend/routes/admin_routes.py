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
            "message": str(e)
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
@require_permission('can_delete_personnel')
def delete_admin():
    try:
        data = request.json
        if 'id' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少管理員ID"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查管理員是否存在
            cursor.execute("""
                SELECT id FROM administrators 
                WHERE id = %s AND status = 'active'
            """, (data['id'],))
            if not cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "管理員不存在"
                }), 404

            # 軟刪除管理員
            cursor.execute("""
                UPDATE administrators 
                SET status = 'inactive', updated_at = NOW()
                WHERE id = %s
            """, (data['id'],))
            
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
            "message": str(e)
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