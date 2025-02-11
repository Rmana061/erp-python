from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from backend.utils.password_utils import hash_password
import datetime

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/customer/list', methods=['POST'])
def get_customer_list():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, 
                       email, address, line_account, viewable_products, remark,
                       created_at, updated_at 
                FROM customers 
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            customers = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 格式化日期並調整欄位名稱
            for customer in customers:
                if customer['created_at']:
                    customer['created_at'] = customer['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if customer['updated_at']:
                    customer['updated_at'] = customer['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                # 將 contact_name 映射為 contact_person 以匹配前端
                if 'contact_name' in customer:
                    customer['contact_person'] = customer['contact_name']
                    del customer['contact_name']
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": customers
            })
    except Exception as e:
        print(f"Error in get_customer_list: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/add', methods=['POST'])
def add_customer():
    try:
        data = request.json
        
        # 檢查必要欄位
        required_fields = ['username', 'password', 'company_name', 'contact_person', 
                         'phone', 'email', 'address']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({
                    "status": "error",
                    "message": f"缺少必要欄位: {field}"
                }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查用戶名是否已存在
            cursor.execute("""
                SELECT id FROM customers 
                WHERE username = %s AND status = 'active'
            """, (data['username'],))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "用戶名已存在"
                }), 400
            
            # 檢查信箱是否已存在
            cursor.execute("""
                SELECT id FROM customers 
                WHERE email = %s AND status = 'active'
            """, (data['email'],))
            if cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "信箱已存在"
                }), 400
            
            # 密碼加密
            hashed_password = hash_password(data['password'])
            
            # 插入新客戶
            cursor.execute("""
                INSERT INTO customers (
                    username, password, company_name, contact_name, 
                    phone, email, address, line_account, viewable_products, remark,
                    status, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'active', NOW(), NOW()
                ) RETURNING id
            """, (
                data['username'], hashed_password, data['company_name'],
                data['contact_person'], data['phone'], data['email'],
                data['address'], data.get('line_account', ''),
                data.get('viewable_products', ''), data.get('remark', '')
            ))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客戶新增成功",
                "id": new_id
            })
            
    except Exception as e:
        print(f"Error in add_customer: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/update', methods=['PUT'])
def update_customer():
    try:
        data = request.json
        if 'id' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少客戶ID"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查客戶是否存在
            cursor.execute("""
                SELECT id FROM customers 
                WHERE id = %s AND status = 'active'
            """, (data['id'],))
            if not cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "客戶不存在"
                }), 404
            
            # 檢查用戶名是否重複
            if 'username' in data:
                cursor.execute("""
                    SELECT id FROM customers 
                    WHERE username = %s AND id != %s AND status = 'active'
                """, (data['username'], data['id']))
                if cursor.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "用戶名已存在"
                    }), 400
            
            # 檢查信箱是否重複
            if 'email' in data:
                cursor.execute("""
                    SELECT id FROM customers 
                    WHERE email = %s AND id != %s AND status = 'active'
                """, (data['email'], data['id']))
                if cursor.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "信箱已存在"
                    }), 400
            
            # 構建更新語句
            update_fields = []
            update_values = []
            
            field_mapping = {
                'username': 'username',
                'company_name': 'company_name',
                'contact_person': 'contact_name',
                'phone': 'phone',
                'email': 'email',
                'address': 'address',
                'line_account': 'line_account',
                'viewable_products': 'viewable_products',
                'remark': 'remark'
            }
            
            for key, field in field_mapping.items():
                if key in data and data[key] is not None:
                    update_fields.append(f"{field} = %s")
                    update_values.append(data[key])
            
            # 如果有密碼更新
            if 'password' in data and data['password']:
                update_fields.append("password = %s")
                update_values.append(hash_password(data['password']))
            
            if not update_fields:
                return jsonify({
                    "status": "error",
                    "message": "沒有提供要更新的欄位"
                }), 400
            
            # 添加更新時間
            update_fields.append("updated_at = NOW()")
            
            # 執行更新
            update_values.append(data['id'])
            update_query = f"""
                UPDATE customers 
                SET {', '.join(update_fields)}
                WHERE id = %s AND status = 'active'
            """
            
            cursor.execute(update_query, tuple(update_values))
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客戶資料更新成功"
            })
            
    except Exception as e:
        print(f"Error in update_customer: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/delete', methods=['POST'])
def delete_customer():
    try:
        data = request.json
        if 'id' not in data:
            return jsonify({
                "status": "error",
                "message": "缺少客戶ID"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查客戶是否存在
            cursor.execute("""
                SELECT id FROM customers 
                WHERE id = %s AND status = 'active'
            """, (data['id'],))
            if not cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "客戶不存在"
                }), 404
            
            # 軟刪除客戶
            cursor.execute("""
                UPDATE customers 
                SET status = 'inactive', updated_at = NOW()
                WHERE id = %s
            """, (data['id'],))
            
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客戶刪除成功"
            })
            
    except Exception as e:
        print(f"Error in delete_customer: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/info', methods=['POST'])
def get_customer_info():
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        
        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "未登入或登入已過期"
            }), 401

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查询客户信息
            cursor.execute("""
                SELECT id, username, company_name, contact_name, 
                       phone, email, address, line_account, viewable_products
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404
                
            # 构建返回数据
            columns = ['id', 'username', 'company_name', 'contact_name', 
                      'phone', 'email', 'address', 'line_account', 'viewable_products']
            customer_data = dict(zip(columns, result))
            
            # 将 contact_name 映射为 contact_person
            if 'contact_name' in customer_data:
                customer_data['contact_person'] = customer_data['contact_name']
                del customer_data['contact_name']
            
            return jsonify({
                "status": "success",
                "data": customer_data
            })

    except Exception as e:
        print(f"Error in get_customer_info: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/<int:customer_id>/info', methods=['POST'])
def get_customer_detail(customer_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查询客户信息
            cursor.execute("""
                SELECT id, username, company_name, contact_name, 
                       phone, email, address, line_account, viewable_products, remark
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404

            # 构建返回数据
            columns = ['id', 'username', 'company_name', 'contact_name', 
                      'phone', 'email', 'address', 'line_account', 'viewable_products', 'remark']
            customer_data = dict(zip(columns, result))
            
            # 将 contact_name 映射为 contact_person
            if 'contact_name' in customer_data:
                customer_data['contact_person'] = customer_data['contact_name']
                del customer_data['contact_name']

            return jsonify({
                "status": "success",
                "data": customer_data
            })

    except Exception as e:
        print(f"Error in get_customer_detail: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/line/unbind', methods=['POST'])
def unbind_line():
    try:
        # 尝试从 cookie 获取 customer_id
        customer_id = request.cookies.get('customer_id')
        
        # 如果 cookie 中没有，则从请求体获取
        if not customer_id:
            data = request.get_json()
            customer_id = data.get('customer_id') if data else None
            
        print(f"Customer ID: {customer_id}")

        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "未登入或登入已過期"
            }), 401

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 更新客户的 line_account 为 NULL
            cursor.execute("""
                UPDATE customers 
                SET line_account = NULL,
                    updated_at = NOW()
                WHERE id = %s AND status = 'active'
                RETURNING id;
            """, (customer_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404

            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "LINE帳號解除綁定成功"
            })

    except Exception as e:
        print(f"Error in unbind_line: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 