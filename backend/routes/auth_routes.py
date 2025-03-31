from flask import Blueprint, request, jsonify, session
import bcrypt
from backend.config.database import get_db_connection
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM customers WHERE username = %s AND status = 'active'",
                (data['username'],)
            )
            customer = cursor.fetchone()
            
            if customer:
                if bcrypt.checkpw(data['password'].encode('utf-8'), customer['password'].encode('utf-8')):
                    session['customer_id'] = customer['id']
                    session['company_name'] = customer['company_name']
                    session.modified = True
                    
                    return jsonify({
                        'status': 'success',
                        'message': '登入成功',
                        'data': {
                            'customer_id': customer['id'],
                            'company_name': customer['company_name']
                        }
                    })
                else:
                    return jsonify({'status': 'error', 'message': '密碼錯誤'})
            else:
                return jsonify({'status': 'error', 'message': '帳號不存在或已停用'})
    except Exception as e:
        logger.error("Error in login: %s", str(e))
        return jsonify({'status': 'error', 'message': '登入失敗'})

@auth_bp.route('/customer-login', methods=['POST'])
def customer_login():
    try:
        data = request.get_json()
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM customers WHERE username = %s AND status = 'active'",
                (data['username'],)
            )
            customer = cursor.fetchone()
            
            if customer:
                # 獲取列名
                columns = [desc[0] for desc in cursor.description]
                # 將元組轉換為字典
                customer_dict = dict(zip(columns, customer))
                
                if bcrypt.checkpw(data['password'].encode('utf-8'), customer_dict['password'].encode('utf-8')):
                    session['customer_id'] = customer_dict['id']
                    session['company_name'] = customer_dict['company_name']
                    session.modified = True
                    
                    return jsonify({
                        'status': 'success',
                        'message': '登入成功',
                        'data': {
                            'customer_id': customer_dict['id'],
                            'company_name': customer_dict['company_name']
                        }
                    })
                else:
                    return jsonify({'status': 'error', 'message': '密碼錯誤'})
            else:
                return jsonify({'status': 'error', 'message': '帳號不存在或已停用'})
    except Exception as e:
        logger.error("Error in customer_login: %s", str(e))
        return jsonify({'status': 'error', 'message': '登入失敗'})

@auth_bp.route('/admin-login', methods=['POST'])
def admin_login():
    try:
        logger.info("開始處理管理員登入...")
        data = request.get_json()
        
        # 驗證請求數據
        if not data or 'admin_account' not in data or 'admin_password' not in data:
            logger.warning("管理員登入請求缺少必要參數")
            return jsonify({'status': 'error', 'message': '請提供用戶名和密碼'})

        logger.debug("接收到的登入數據: %s", data)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT a.*, p.*
                FROM administrators a
                JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.admin_account = %s AND a.status = 'active'
                """,
                (data['admin_account'],)
            )
            admin = cursor.fetchone()
            
            logger.debug("查詢到的管理員信息: %s", admin)

            if not admin:
                return jsonify({'status': 'error', 'message': '帳號不存在或已停用'})

            # 將查詢結果轉換為字典
            admin_data = {
                'id': admin[0],
                'admin_account': admin[1],
                'admin_name': admin[3],
                'admin_password': admin[2],
                'staff_no': admin[4],
                'permission_level_id': admin[5]
            }

            # 獲取權限信息
            permissions = {
                'can_approve_orders': bool(admin[11]),
                'can_edit_orders': bool(admin[12]),
                'can_close_order_dates': bool(admin[13]),
                'can_add_customer': bool(admin[14]),
                'can_add_product': bool(admin[15]),
                'can_add_personnel': bool(admin[16]),
                'can_view_system_logs': bool(admin[17]),
                'can_decide_product_view': bool(admin[18])
            }

            # 驗證密碼
            if bcrypt.checkpw(data['admin_password'].encode('utf-8'), admin_data['admin_password'].encode('utf-8')):
                # 清除舊的 session
                session.clear()
                
                # 設置session
                session['admin_id'] = admin_data['id']
                session['admin_account'] = admin_data['admin_account']
                session['admin_name'] = admin_data['admin_name']
                session['permissions'] = permissions
                session.permanent = True
                session.modified = True
                
                logger.debug("設置的 session: %s", dict(session))

                response_data = {
                    'status': 'success',
                    'message': '登入成功',
                    'data': {
                        'id': admin_data['id'],
                        'admin_account': admin_data['admin_account'],
                        'admin_name': admin_data['admin_name'],
                        'staff_no': admin_data['staff_no'],
                        'permission_level_id': admin_data['permission_level_id'],
                        'permissions': permissions
                    }
                }
                
                logger.debug("返回的數據: %s", response_data)
                return jsonify(response_data)
            else:
                return jsonify({'status': 'error', 'message': '密碼錯誤'})
    except Exception as e:
        logger.error("管理員登入錯誤: %s", str(e))
        return jsonify({'status': 'error', 'message': '登入失敗'})

@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json()
        
        # 生成新的加密密碼
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(data['new_password'].encode('utf-8'), salt)
        logger.debug("新的加密密碼: %s", hashed_password)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 驗證舊密碼
            cursor.execute(
                "SELECT password FROM customers WHERE id = %s",
                (data['customer_id'],)
            )
            result = cursor.fetchone()
            
            if not result:
                return jsonify({'status': 'error', 'message': '找不到該用戶'})
            
            if not bcrypt.checkpw(data['old_password'].encode('utf-8'), result['password'].encode('utf-8')):
                return jsonify({'status': 'error', 'message': '舊密碼錯誤'})
            
            # 更新密碼
            cursor.execute(
                "UPDATE customers SET password = %s WHERE id = %s",
                (hashed_password.decode('utf-8'), data['customer_id'])
            )
            conn.commit()
            
            return jsonify({'status': 'success', 'message': '密碼重置成功'})
    except Exception as e:
        logger.error("重置密碼錯誤: %s", str(e))
        return jsonify({'status': 'error', 'message': '密碼重置失敗'}) 