from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.utils.password_utils import hash_password
import datetime
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
def add_admin():
    try:
        data = request.json
        
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
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({"status": "error", "message": "未登入或登入已過期"}), 401

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            cursor.execute("""
                SELECT id, admin_account, admin_name, staff_no, permission_level_id
                FROM administrators 
                WHERE id = %s AND status = 'active'
            """, (admin_id,))
            
            admin_data = cursor.fetchone()
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": {
                    "id": admin_data['id'],
                    "admin_account": admin_data['admin_account'],
                    "admin_name": admin_data['admin_name'],
                    "staff_no": admin_data['staff_no'],
                    "permission_level_id": admin_data['permission_level_id']
                }
            })

    except Exception as e:
        print(f"Error in get_admin_info: {str(e)}")
        return jsonify({"status": "error", "message": "獲取管理員資訊失敗"}), 500

@admin_bp.route('/admin/info/<int:admin_id>', methods=['POST'])
def get_admin_detail(admin_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            cursor.execute("""
                SELECT id, admin_account, admin_name, staff_no, permission_level_id
                FROM administrators 
                WHERE id = %s AND status = 'active'
            """, (admin_id,))
            
            admin_data = cursor.fetchone()
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": {
                    "id": admin_data['id'],
                    "admin_account": admin_data['admin_account'],
                    "admin_name": admin_data['admin_name'],
                    "staff_no": admin_data['staff_no'],
                    "permission_level_id": admin_data['permission_level_id']
                }
            })

    except Exception as e:
        print(f"Error in get_admin_detail: {str(e)}")
        return jsonify({"status": "error", "message": "獲取管理員資訊失敗"}), 500 