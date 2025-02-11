from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.utils.password_utils import verify_password

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
        data = request.json
        if not data or 'admin_account' not in data or 'admin_password' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少必要的登入資訊"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查询管理员信息
            cursor.execute("""
                SELECT id, admin_account, admin_name, admin_password, staff_no, permission_level_id
                FROM administrators 
                WHERE admin_account = %s AND status = 'active'
            """, (data['admin_account'],))
            
            admin = cursor.fetchone()
            
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
                'admin_name': admin[2],
                'admin_password': admin[3],
                'staff_no': admin[4],
                'permission_level_id': admin[5]
            }

            # 验证密码
            if not verify_password(data['admin_password'], admin_data['admin_password']):
                cursor.close()
                return jsonify({
                    "status": "error",
                    "message": "帳號或密碼錯誤"
                }), 401
                
            cursor.close()

            # 设置 session
            session['admin_id'] = admin_data['id']
            session['admin_account'] = admin_data['admin_account']
            
            # 返回管理员信息
            return jsonify({
                "status": "success",
                "message": "登入成功",
                "data": {
                    "id": admin_data['id'],
                    "admin_account": admin_data['admin_account'],
                    "admin_name": admin_data['admin_name'],
                    "staff_no": admin_data['staff_no'],
                    "permission_level_id": admin_data['permission_level_id']
                }
            })

    except Exception as e:
        print(f"Error in admin_login: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "登入失敗，請稍後再試"
        }), 500 