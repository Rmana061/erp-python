from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from hash_password import verify_password, hash_password

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, admin_account, admin_password 
                FROM administrators 
                WHERE admin_account = %s 
                AND status = 'active'
            """, (data['username'],))
            
            user = cursor.fetchone()
            if user is None:
                return jsonify({"error": "帳號或密碼錯誤"}), 401
                
            if not verify_password(data['password'], user[2]):
                return jsonify({"error": "帳號或密碼錯誤"}), 401
                
            cursor.close()
            
            response = jsonify({
                "message": "Login successful",
                "user_id": user[0]
            })
            
            return response
            
    except Exception as e:
        print(f"Error in login: {str(e)}")
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/customer-login', methods=['POST'])
def customer_login():
    try:
        data = request.json
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, password, company_name 
                FROM customers 
                WHERE username = %s 
                AND status = 'active'
            """, (data['username'],))
            
            customer = cursor.fetchone()
            if customer is None:
                return jsonify({"error": "帳號或密碼錯誤"}), 401
                
            if not verify_password(data['password'], customer[2]):
                return jsonify({"error": "帳號或密碼錯誤"}), 401
                
            cursor.close()
            
            # 设置 session
            session.clear()  # 清除旧的session
            session['customer_id'] = customer[0]
            session['username'] = customer[1]
            session['company_name'] = customer[3]
            session.permanent = True  # 使session持久化
            
            response = jsonify({
                "status": "success",
                "message": "登入成功",
                "data": {
                    "customer_id": customer[0],
                    "username": customer[1],
                    "company_name": customer[3]
                }
            })
            
            return response
            
    except Exception as e:
        print(f"Error in customer_login: {str(e)}")
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    try:
        print("開始處理管理員登入...")
        data = request.json
        if not data or 'admin_account' not in data or 'admin_password' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少必要的登入資訊"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查询管理员信息和权限
            cursor.execute("""
                SELECT a.*, p.*
                FROM administrators a
                JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.admin_account = %s AND a.status = 'active'
            """, (data['admin_account'],))
            
            admin = cursor.fetchone()
            print(f"查詢到的管理員信息: {admin}")
            
            if admin is None:
                cursor.close()
                return jsonify({
                    "status": "error",
                    "message": "帳號或密碼錯誤"
                }), 401

            # 将查询结果转换为字典
            admin_data = {
                'id': admin[0],
                'admin_account': admin[1],
                'admin_name': admin[3],  # 修正索引
                'admin_password': admin[2],  # 修正索引，這是加密後的密碼
                'staff_no': admin[4],
                'permission_level_id': admin[5]
            }

            # 获取权限信息
            permissions = {
                'can_approve_orders': bool(admin[11]),  # 修正索引
                'can_edit_orders': bool(admin[12]),
                'can_close_order_dates': bool(admin[13]),
                'can_add_customer': bool(admin[14]),
                'can_add_product': bool(admin[15]),
                'can_add_personnel': bool(admin[16]),
                'can_view_system_logs': bool(admin[17]),
                'can_decide_product_view': bool(admin[18])
            }

            print(f"驗證密碼...")
            print(f"輸入的密碼: {data['admin_password']}")
            print(f"數據庫中的加密密碼: {admin_data['admin_password']}")
            
            # 验证密码
            if not verify_password(data['admin_password'], admin_data['admin_password']):
                cursor.close()
                return jsonify({
                    "status": "error",
                    "message": "帳號或密碼錯誤"
                }), 401
                
            cursor.close()

            # 清除舊的 session
            session.clear()
            
            # 设置 session
            session['admin_id'] = admin_data['id']
            session['admin_account'] = admin_data['admin_account']
            session['admin_name'] = admin_data['admin_name']
            session['permissions'] = permissions
            
            # 設置 session 持久化
            session.permanent = True
            
            print(f"設置的 session: {dict(session)}")
            
            # 返回管理员信息
            response_data = {
                "status": "success",
                "message": "登入成功",
                "data": {
                    "id": admin_data['id'],
                    "admin_account": admin_data['admin_account'],
                    "admin_name": admin_data['admin_name'],
                    "staff_no": admin_data['staff_no'],
                    "permission_level_id": admin_data['permission_level_id'],
                    "permissions": permissions
                }
            }
            print(f"返回的數據: {response_data}")
            return jsonify(response_data)

    except Exception as e:
        print(f"管理員登入錯誤: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "登入失敗，請稍後再試"
        }), 500

@auth_bp.route('/reset-admin-password', methods=['POST'])
def reset_admin_password():
    try:
        data = request.json
        if not data or 'admin_account' not in data or 'new_password' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少必要的資訊"
            }), 400

        # 對新密碼進行加密
        hashed_password = hash_password(data['new_password'])
        print(f"新的加密密碼: {hashed_password}")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 更新管理員密碼
            cursor.execute("""
                UPDATE administrators 
                SET admin_password = %s,
                    updated_at = NOW()
                WHERE admin_account = %s
                RETURNING id
            """, (hashed_password, data['admin_account']))
            
            updated = cursor.fetchone()
            conn.commit()
            cursor.close()
            
            if not updated:
                return jsonify({
                    "status": "error",
                    "message": "管理員不存在"
                }), 404

            return jsonify({
                "status": "success",
                "message": "密碼重置成功"
            })

    except Exception as e:
        print(f"重置密碼錯誤: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "重置密碼失敗，請稍後再試"
        }), 500 