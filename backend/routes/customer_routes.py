from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from hash_password import verify_password, hash_password
import datetime
from typing import Dict, Any
import psycopg2.extras

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/customer/list', methods=['POST'])
def get_customer_list():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, 
                       email, address, line_account, viewable_products, remark,
                       created_at, updated_at, reorder_limit_days
                FROM customers 
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            print("数据库列名:", columns)  # 打印列名
            customers = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 打印每个客户的reorder_limit_days值
            for i, customer in enumerate(customers):
                print(f"客户[{i+1}] {customer.get('company_name')} 的reorder_limit_days值:", customer.get('reorder_limit_days'))
            
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
                
                # 确保reorder_limit_days是数字类型
                if 'reorder_limit_days' in customer:
                    try:
                        if customer['reorder_limit_days'] is None:
                            customer['reorder_limit_days'] = 0
                        else:
                            customer['reorder_limit_days'] = int(customer['reorder_limit_days'])
                    except (ValueError, TypeError):
                        customer['reorder_limit_days'] = 0
                else:
                    customer['reorder_limit_days'] = 0
            
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
                    reorder_limit_days, status, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, 'active', NOW(), NOW()
                ) RETURNING id
            """, (
                data['username'], hashed_password, data['company_name'],
                data['contact_person'], data['phone'], data['email'],
                data['address'], data.get('line_account', ''),
                data.get('viewable_products', ''), data.get('remark', ''),
                data.get('reorder_limit_days', 2)
            ))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            
            # 記錄操作日誌
            try:
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 獲取當前登入管理員ID
                admin_id = session.get('admin_id')
                if admin_id:
                    # 準備客戶資料用於日誌 - 完整記錄所有客戶欄位
                    customer_data = {
                        'id': new_id,
                        'username': data['username'],
                        'company_name': data['company_name'],
                        'contact_person': data['contact_person'], 
                        'phone': data['phone'],
                        'email': data['email'],
                        'address': data['address'],
                        'line_account': data.get('line_account', ''),
                        'viewable_products': data.get('viewable_products', ''),
                        'remark': data.get('remark', ''),
                        'reorder_limit_days': data.get('reorder_limit_days', 0)
                    }
                    
                    # 初始化日誌服務並記錄操作
                    log_service = LogServiceRegistry.get_service(conn, 'customers')
                    log_service.log_operation(
                        table_name='customers',
                        operation_type='新增',
                        record_id=new_id,
                        old_data=None,
                        new_data=customer_data,
                        performed_by=admin_id,
                        user_type='管理員'
                    )
            except Exception as log_error:
                # 日誌記錄失敗不影響主要功能
                print(f"Error logging customer add operation: {str(log_error)}")
            
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
        # 使用 session 来获取当前管理员 ID
        current_admin_id = session.get('admin_id')
        if not current_admin_id:
            return jsonify({"status": "error", "message": "未登录或会话已过期"}), 401
        
        # 获取数据
        data = request.get_json()
        
        # 获取旧数据
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT * FROM customers WHERE id = %s", (data['id'],))
            old_data = dict(cursor.fetchone())
        
        # 检查是否是密码修改操作
        password_changed = False
        if 'password' in data and data['password'] != old_data.get('password'):
            password_changed = True
        
        # 更新客户信息
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
            
            # 在更新之前獲取舊的客戶資料用於日誌記錄
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address,
                       line_account, viewable_products, remark, reorder_limit_days
                FROM customers WHERE id = %s AND status = 'active'
            """, (data['id'],))
            old_customer = cursor.fetchone()
            old_customer_data = None
            if old_customer:
                old_customer_data = {
                    'id': old_customer[0],
                    'username': old_customer[1],
                    'company_name': old_customer[2],
                    'contact_person': old_customer[3],
                    'phone': old_customer[4],
                    'email': old_customer[5],
                    'address': old_customer[6],
                    'line_account': old_customer[7],
                    'viewable_products': old_customer[8],
                    'remark': old_customer[9],
                    'reorder_limit_days': old_customer[10] if len(old_customer) > 10 else 0
                }
            
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
                'remark': 'remark',
                'reorder_limit_days': 'reorder_limit_days'
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
            
            # 准备新客户数据用于日志记录
            new_customer_data = {
                'id': data['id'],
                'username': data['username'],
                'company_name': data['company_name'],
                'contact_person': data['contact_person'],
                'phone': data['phone'],
                'email': data['email'],
                'address': data['address'],
                'line_account': data.get('line_account', ''),
                'viewable_products': data.get('viewable_products', ''),
                'remark': data.get('remark', ''),
                'reorder_limit_days': data.get('reorder_limit_days', 0)
            }
            
            # 如果是密码修改，直接添加标记到new_data中
            if password_changed:
                new_customer_data['password_changed'] = True
            
            try:
                # 记录日志
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 初始化日志服务并记录操作
                log_service = LogServiceRegistry.get_service(conn, 'customers')
                log_service.log_operation(
                    table_name='customers',
                    operation_type='修改',
                    record_id=data['id'],
                    old_data=old_customer_data,
                    new_data=new_customer_data,
                    performed_by=current_admin_id,
                    user_type='管理員'
                )
            except Exception as log_error:
                # 日志记录失败不影响主要功能
                print(f"Error logging customer update operation: {str(log_error)}")
            
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
            
            # 檢查客戶是否存在並獲取資料用於日誌記錄
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address,
                       line_account, viewable_products, remark, reorder_limit_days
                FROM customers WHERE id = %s AND status = 'active'
            """, (data['id'],))
            customer = cursor.fetchone()
            
            if not customer:
                return jsonify({
                    "status": "error",
                    "message": "客戶不存在"
                }), 404
            
            # 準備客戶資料用於日誌 - 完整記錄所有客戶欄位
            customer_data = {
                'id': customer[0],
                'username': customer[1],
                'company_name': customer[2],
                'contact_person': customer[3],
                'phone': customer[4],
                'email': customer[5],
                'address': customer[6],
                'line_account': customer[7],
                'viewable_products': customer[8],
                'remark': customer[9],
                'reorder_limit_days': customer[10] if len(customer) > 10 else 0
            }
            
            # 軟刪除客戶
            cursor.execute("""
                UPDATE customers 
                SET status = 'inactive', updated_at = NOW()
                WHERE id = %s
            """, (data['id'],))
            
            conn.commit()
            
            # 記錄刪除操作的日誌
            try:
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 獲取當前登入管理員ID
                admin_id = session.get('admin_id')
                if admin_id:
                    # 初始化日誌服務並記錄操作
                    log_service = LogServiceRegistry.get_service(conn, 'customers')
                    log_service.log_operation(
                        table_name='customers',
                        operation_type='刪除',
                        record_id=data['id'],
                        old_data=customer_data,
                        new_data=None,
                        performed_by=admin_id,
                        user_type='管理員'
                    )
            except Exception as log_error:
                # 日誌記錄失敗不影響主要功能
                print(f"Error logging customer delete operation: {str(log_error)}")
            
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
                       phone, email, address, line_account, viewable_products, reorder_limit_days
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
                      'phone', 'email', 'address', 'line_account', 'viewable_products', 'reorder_limit_days']
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
            
            # 查询客户信息，添加更多字段
            cursor.execute("""
                SELECT id, username, company_name, contact_name, 
                       phone, email, address, line_account, viewable_products, 
                       remark, created_at, updated_at, status, reorder_limit_days
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404

            # 构建返回数据，添加更多字段
            columns = ['id', 'username', 'company_name', 'contact_name', 
                      'phone', 'email', 'address', 'line_account', 
                      'viewable_products', 'remark', 'created_at', 
                      'updated_at', 'status', 'reorder_limit_days']
            customer_data = dict(zip(columns, result))
            
            # 格式化日期
            if customer_data.get('created_at'):
                customer_data['created_at'] = customer_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if customer_data.get('updated_at'):
                customer_data['updated_at'] = customer_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
            
            # 将 contact_name 映射为 contact_person
            if 'contact_name' in customer_data:
                customer_data['contact_person'] = customer_data['contact_name']
                del customer_data['contact_name']

            print("返回的客户数据:", customer_data)  # 添加调试日志
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

def _process_create(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
    """處理客戶新增操作"""
    try:
        customer_info = {}
        
        # 從新數據中提取客戶信息 - 完整記錄所有客戶欄位
        if isinstance(new_data, dict):
            customer_info = {
                'id': new_data.get('id', ''),
                'username': new_data.get('username', ''),
                'company_name': new_data.get('company_name', ''),
                'contact_person': new_data.get('contact_person', ''),
                'phone': new_data.get('phone', ''),
                'email': new_data.get('email', ''),
                'address': new_data.get('address', ''),
                'line_account': new_data.get('line_account', ''),
                'viewable_products': new_data.get('viewable_products', ''),
                'remark': new_data.get('remark', ''),
                'reorder_limit_days': new_data.get('reorder_limit_days', 0)
            }
        
        return {
            'message': {
                'customer': customer_info
            },
            'operation_type': '新增'
        }
    except Exception as e:
        print(f"Error processing customer create: {str(e)}")
        return {'message': '處理客戶新增時發生錯誤', 'operation_type': None}

def _process_update(self, old_data, new_data):
    try:
        changes = {}
        
        # 检查是否有密码变更标记
        if new_data.get('password_changed', False):
            return {
                'message': {
                    'customer_id': new_data.get('id', ''),
                    'password_changed': True
                },
                'operation_type': '密碼修改'
            }
        
        # 比較並記錄變更 - 檢查所有客戶欄位
        fields_to_check = [
            'username', 
            'company_name', 
            'contact_person', 
            'phone', 
            'email', 
            'address', 
            'line_account', 
            'viewable_products', 
            'remark'
        ]
        
        for field in fields_to_check:
            old_value = old_data.get(field, '')
            new_value = new_data.get(field, '')
            
            if old_value != new_value:
                changes[field] = {
                    'before': old_value,
                    'after': new_value
                }
        
        if changes:
            # 保存新舊數據以供參考
            return {
                'message': {
                    'customer_id': new_data.get('id', ''),
                    'old_data': old_data,
                    'new_data': new_data,
                    'changes': changes
                },
                'operation_type': '修改'
            }
        
        return {'message': '無變更', 'operation_type': None}
    except Exception as e:
        print(f"Error processing customer update: {str(e)}")
        return {'message': '處理客戶修改時發生錯誤', 'operation_type': None} 