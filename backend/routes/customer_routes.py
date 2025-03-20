from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from hash_password import verify_password, hash_password
import datetime
from typing import Dict, Any
import psycopg2.extras
import os
import time
import jwt
from urllib.parse import quote

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/customer/list', methods=['POST'])
def get_customer_list():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, 
                       email, address, viewable_products, remark,
                       created_at, updated_at, reorder_limit_days
                FROM customers 
                WHERE status = 'active'
                ORDER BY created_at DESC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            print("数据库列名:", columns)  # 打印列名
            customers = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 获取每个客户的LINE用户和群组
            for customer in customers:
                # 查询LINE用户
                cursor.execute("""
                    SELECT id, line_user_id, user_name
                    FROM line_users
                    WHERE customer_id = %s
                """, (customer['id'],))
                line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                customer['line_users'] = line_users
                
                # 查询LINE群组
                cursor.execute("""
                    SELECT id, line_group_id, group_name
                    FROM line_groups
                    WHERE customer_id = %s
                """, (customer['id'],))
                line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
                customer['line_groups'] = line_groups
                
                # 为向后兼容，添加空的line_account字段
                customer['line_account'] = ''
            
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
            
            # 使用_process_create函數處理客戶創建邏輯
            customer_id, error_message = _process_create(data, cursor, conn)
            
            if not customer_id:
                conn.rollback()
                return jsonify({
                    "status": "error",
                    "message": error_message or "創建客戶失敗"
                }), 400
            
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客戶新增成功",
                "id": customer_id
            })
            
    except Exception as e:
        print(f"Error in add_customer: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/update', methods=['POST', 'PUT'])
def update_customer():
    """更新客户信息"""
    try:
        # 获取请求数据
        data = request.get_json()
        customer_id = data.get('id')
        
        if not customer_id:
                return jsonify({
                    "status": "error",
                "message": "缺少客户ID"
                    }), 400
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 检查是否有前端传来的原始数据
            original_data = data.get('original_data')
            
            # 使用_process_update函数处理客户更新逻辑
            success, error_message = _process_update(customer_id, data, cursor, conn, original_data)
            
            if not success:
                conn.rollback()
                return jsonify({
                    "status": "error",
                    "message": error_message or "更新客户失败"
                }), 400
            
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客户更新成功"
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
                       viewable_products, remark, reorder_limit_days
                FROM customers WHERE id = %s AND status = 'active'
            """, (data['id'],))
            customer = cursor.fetchone()
            
            if not customer:
                return jsonify({
                    "status": "error",
                    "message": "客戶不存在"
                }), 404
            
            # 準備客戶資料用於日誌 - 完整記錄所有客戶欄位
            customer_data = dict(zip(['id', 'username', 'company_name', 'contact_name', 
                                     'phone', 'email', 'address', 
                                     'viewable_products', 'remark', 'reorder_limit_days'], 
                                     customer))
            
            # 將 contact_name 映射為 contact_person
            if 'contact_name' in customer_data:
                customer_data['contact_person'] = customer_data['contact_name']
                
            # 獲取客戶的LINE用戶和群組
            # 獲取LINE用戶
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (data['id'],))
            line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            customer_data['line_users'] = line_users
            
            # 獲取LINE群組
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (data['id'],))
            line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            customer_data['line_groups'] = line_groups
            
            # 為向後兼容，添加空的line_account字段
            customer_data['line_account'] = ''
            
            # 軟刪除客戶
            cursor.execute("""
                UPDATE customers 
                SET status = 'inactive', updated_at = NOW()
                WHERE id = %s
            """, (data['id'],))
            
            # 刪除LINE用戶和群組關聯
            cursor.execute("DELETE FROM line_users WHERE customer_id = %s", (data['id'],))
            cursor.execute("DELETE FROM line_groups WHERE customer_id = %s", (data['id'],))
            
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
                       phone, email, address, viewable_products, reorder_limit_days
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
                      'phone', 'email', 'address', 'viewable_products', 'reorder_limit_days']
            customer_data = dict(zip(columns, result))
            
            # 将 contact_name 映射为 contact_person
            if 'contact_name' in customer_data:
                customer_data['contact_person'] = customer_data['contact_name']
                # 保留 contact_name 字段，确保两种命名方式都可用
                # del customer_data['contact_name']
            
            # 获取LINE用户列表
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            customer_data['line_users'] = line_users
            
            # 获取LINE群组列表
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            customer_data['line_groups'] = line_groups
            
            # 为向后兼容，添加空的line_account字段
            customer_data['line_account'] = ''
            
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
                       phone, email, address, viewable_products, 
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
                      'phone', 'email', 'address', 'viewable_products', 
                      'remark', 'created_at', 'updated_at', 'status', 'reorder_limit_days']
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
            
            # 获取LINE用户列表
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            customer_data['line_users'] = line_users
            
            # 获取LINE群组列表
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            customer_data['line_groups'] = line_groups
            
            # 为向后兼容，添加空的line_account字段
            customer_data['line_account'] = ''

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
        # 此函數已不再使用，請改用unbind_line_user或unbind_line_group
        return jsonify({
            "status": "error",
            "message": "此API已棄用，請使用/line/unbind-user或/line/unbind-group"
        }), 410

    except Exception as e:
        print(f"Error in unbind_line: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/customer/update-self', methods=['POST'])
def update_customer_self():
    try:
        # 獲取請求數據
        data = request.get_json()
        customer_id = data.get('customer_id')

        if not customer_id:
            return jsonify({"status": "error", "message": "缺少必要參數"}), 400
        
        # 準備需要更新的欄位
        update_fields = {}
        valid_fields = ['company_name', 'contact_name', 'phone', 'email', 'address', 'password']
        
        for field in valid_fields:
            if field in data and data[field]:
                update_fields[field] = data[field]
        
        # 如果沒有任何欄位需要更新
        if not update_fields:
            return jsonify({"status": "error", "message": "無更新資料"}), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # 首先獲取客戶當前資料（用於記錄變更）
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address, 
                       viewable_products, remark, reorder_limit_days
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            old_data_row = cursor.fetchone()
            if not old_data_row:
                return jsonify({"status": "error", "message": "找不到客戶資料"}), 404
                
            old_customer_data = dict(old_data_row)
            
            # 轉換contact_name為contact_person以保持一致性
            if 'contact_name' in old_customer_data:
                old_customer_data['contact_person'] = old_customer_data['contact_name']
                
            # 获取现有的LINE用户列表
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_users'] = old_line_users
            
            # 获取现有的LINE群组列表
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_groups'] = old_line_groups
            
            # 为向后兼容，添加空的line_account字段
            old_customer_data['line_account'] = ''
                
            # 構建更新SQL
            update_sql = "UPDATE customers SET updated_at = NOW()"
            params = []
            
            # 處理密碼更新
            if 'password' in update_fields:
                password = update_fields.pop('password')
                # 生成密碼雜湊
                import bcrypt
                salt = bcrypt.gensalt()
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
                update_sql += ", password = %s"
                params.append(hashed_password)
                
                # 添加密碼變更標記
                old_customer_data['password_changed'] = True
            
            # 處理其他欄位更新
            for field, value in update_fields.items():
                update_sql += f", {field} = %s"
                params.append(value)
            
            update_sql += " WHERE id = %s AND status = 'active' RETURNING id"
            params.append(customer_id)
            
            cursor.execute(update_sql, tuple(params))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({"status": "error", "message": "更新失敗，可能客戶資料不存在或已被禁用"}), 404
            
            # 獲取更新後的客戶資料
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address, 
                       viewable_products, remark, reorder_limit_days
                FROM customers 
                WHERE id = %s
            """, (customer_id,))
            
            new_data_row = cursor.fetchone()
            new_customer_data = dict(new_data_row)
            
            # 轉換contact_name為contact_person以保持一致性
            if 'contact_name' in new_customer_data:
                new_customer_data['contact_person'] = new_customer_data['contact_name']
            
            # LINE用户和群组保持不变
            new_customer_data['line_users'] = old_line_users
            new_customer_data['line_groups'] = old_line_groups
            new_customer_data['line_account'] = ''
            
            # 添加密码变更标记
            if 'password_changed' in old_customer_data:
                new_customer_data['password_changed'] = True
            
            try:
                # 記錄變更日誌
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 初始化日誌服務並記錄操作
                log_service = LogServiceRegistry.get_service(conn, 'customers')
                log_service.log_operation(
                    table_name='customers',
                    operation_type='修改',
                    record_id=customer_id,
                    old_data=old_customer_data,
                    new_data=new_customer_data,
                    performed_by=customer_id,
                    user_type='客戶'
                )
            except Exception as log_error:
                # 日誌記錄失敗不影響主要功能
                print(f"Error logging customer update: {str(log_error)}")
            
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": "客戶資料更新成功"
            })
        
    except Exception as e:
        print(f"Error in update_customer_self: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def _process_create(customer_data, cursor, conn):
    """处理客户创建逻辑"""
    try:
        # 提取客户信息
        username = customer_data.get('username')
        company_name = customer_data.get('company_name')
        contact_name = customer_data.get('contact_name') or customer_data.get('contact_person')
        phone = customer_data.get('phone')
        email = customer_data.get('email')
        address = customer_data.get('address')
        password = customer_data.get('password')
        viewable_products = customer_data.get('viewable_products')
        remark = customer_data.get('remark')
        reorder_limit_days = customer_data.get('reorder_limit_days', 0)
        
        # 确保reorder_limit_days是整数
        try:
            reorder_limit_days = int(reorder_limit_days) if reorder_limit_days is not None else 0
        except (ValueError, TypeError):
            reorder_limit_days = 0
        
        # 密码加密
        if password:
            import bcrypt
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        else:
            password_hash = None
            
        # 检查用户名是否存在
        if username:
            cursor.execute(
                "SELECT id FROM customers WHERE username = %s AND status = 'active'", 
                (username,)
            )
            if cursor.fetchone():
                return None, "用户名已存在"
        
        # 插入新客户记录
        cursor.execute(
            """
            INSERT INTO customers 
            (username, company_name, contact_name, phone, email, address, password, 
             viewable_products, remark, status, reorder_limit_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
            RETURNING id
            """,
            (username, company_name, contact_name, phone, email, address, password_hash, 
             viewable_products, remark, reorder_limit_days)
        )
        
        customer_id = cursor.fetchone()[0]
        
        # 处理LINE用户列表
        line_users = customer_data.get('line_users', [])
        for user in line_users:
            line_user_id = user.get('line_user_id')
            user_name = user.get('user_name')
            if line_user_id and user_name:
                # 检查此LINE用户ID是否已绑定到其他客户
                cursor.execute(
                    "SELECT customer_id FROM line_users WHERE line_user_id = %s",
                    (line_user_id,)
                )
                existing = cursor.fetchone()
                if existing and existing[0] != customer_id:
                    continue  # 跳过已绑定到其他客户的LINE用户
                
                # 插入LINE用户
                cursor.execute(
                    """
                    INSERT INTO line_users 
                    (line_user_id, user_name, customer_id)
                    VALUES (%s, %s, %s)
                    """,
                    (line_user_id, user_name, customer_id)
                )
        
        # 处理LINE群组列表
        line_groups = customer_data.get('line_groups', [])
        for group in line_groups:
            line_group_id = group.get('line_group_id')
            group_name = group.get('group_name')
            if line_group_id and group_name:
                # 检查此LINE群组ID是否已绑定到其他客户
                cursor.execute(
                    "SELECT customer_id FROM line_groups WHERE line_group_id = %s",
                    (line_group_id,)
                )
                existing = cursor.fetchone()
                if existing and existing[0] != customer_id:
                    continue  # 跳过已绑定到其他客户的LINE群组
                
                # 插入LINE群组
                cursor.execute(
                    """
                    INSERT INTO line_groups 
                    (line_group_id, group_name, customer_id)
                    VALUES (%s, %s, %s)
                    """,
                    (line_group_id, group_name, customer_id)
                )
        
        # 准备日志记录
        old_data = None
        
        # 获取创建后的客户信息
        cursor.execute(
            """
            SELECT id, username, company_name, contact_name, phone, email, address, 
                   viewable_products, remark, created_at, updated_at, status, reorder_limit_days
            FROM customers
            WHERE id = %s
            """,
            (customer_id,)
        )
        
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        new_data = dict(zip(columns, row))
        
        # 转换contact_name为contact_person以保持一致性
        if 'contact_name' in new_data:
            new_data['contact_person'] = new_data['contact_name']
        
        # 添加LINE用户和群组信息
        cursor.execute(
            """
            SELECT id, line_user_id, user_name
            FROM line_users
            WHERE customer_id = %s
            """,
            (customer_id,)
        )
        new_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
        new_data['line_users'] = new_line_users
        
        cursor.execute(
            """
            SELECT id, line_group_id, group_name
            FROM line_groups
            WHERE customer_id = %s
            """,
            (customer_id,)
        )
        new_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
        new_data['line_groups'] = new_line_groups
        
        # 为向后兼容，添加空的line_account字段
        new_data['line_account'] = ''
        
        # 格式化日期
        if 'created_at' in new_data and new_data['created_at']:
            new_data['created_at'] = new_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        if 'updated_at' in new_data and new_data['updated_at']:
            new_data['updated_at'] = new_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        # 添加密码标记
        if password:
            new_data['password_set'] = True
        
        # 记录日志
        try:
            # 获取当前登录的管理员信息
            admin_id = session.get('admin_id')
            
            # 初始化日誌服務並記錄操作
            from backend.services.log_service_registry import LogServiceRegistry
            log_service = LogServiceRegistry.get_service(conn, 'customers')
            log_service.log_operation(
                table_name='customers',
                operation_type='新增',
                record_id=customer_id,
                old_data=old_data,
                new_data=new_data,
                performed_by=admin_id,
                user_type='管理員'
            )
        except Exception as log_error:
            print(f"Error logging customer creation: {str(log_error)}")
        
        return customer_id, None
    
    except Exception as e:
        print(f"Error in _process_create: {str(e)}")
        return None, str(e)

def _process_update(customer_id, customer_data, cursor, conn, original_data=None):
    """处理客户更新逻辑"""
    try:
        # 检查客户是否存在
        cursor.execute(
            "SELECT id FROM customers WHERE id = %s AND status = 'active'", 
            (customer_id,)
        )
        if not cursor.fetchone():
            return False, "客户不存在或已停用"
        
        # 获取旧数据用于记录变更
        old_data = None
        
        # 如果前端提供了原始数据，直接使用它
        if original_data:
            old_data = original_data
        else:
            # 否则从数据库获取旧数据
            cursor.execute(
                """
                SELECT id, username, company_name, contact_name, phone, email, 
                       address, viewable_products, remark, created_at, 
                       updated_at, status, reorder_limit_days
                FROM customers
                WHERE id = %s
                """,
                (customer_id,)
            )
            
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            old_data = dict(zip(columns, row))
            
            # 转换contact_name为contact_person以保持一致性
            if 'contact_name' in old_data:
                old_data['contact_person'] = old_data['contact_name']
            
            # 获取旧的LINE用户列表
            cursor.execute(
                """
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
                """,
                (customer_id,)
            )
            old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            old_data['line_users'] = old_line_users
            
            # 获取旧的LINE群组列表
            cursor.execute(
                """
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
                """,
                (customer_id,)
            )
            old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            old_data['line_groups'] = old_line_groups
            
            # 为向后兼容，添加空的line_account字段
            old_data['line_account'] = ''
            
            # 格式化日期
            if 'created_at' in old_data and old_data['created_at']:
                old_data['created_at'] = old_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if 'updated_at' in old_data and old_data['updated_at']:
                old_data['updated_at'] = old_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        # 提取要更新的字段
        update_fields = []
        update_values = []
        
        # 检查用户名更新
        if 'username' in customer_data and customer_data['username']:
            username = customer_data['username']
            # 检查新用户名是否已被占用
            cursor.execute(
                "SELECT id FROM customers WHERE username = %s AND id != %s AND status = 'active'", 
                (username, customer_id)
            )
            if cursor.fetchone():
                return False, "用户名已存在"
            
            update_fields.append("username = %s")
            update_values.append(username)
        
        # 处理其他常规字段
        field_mapping = {
            'company_name': 'company_name',
            'contact_name': 'contact_name',
            'contact_person': 'contact_name',  # 支持两种字段名
            'phone': 'phone',
            'email': 'email',
            'address': 'address',
            'viewable_products': 'viewable_products',
            'remark': 'remark',
            'reorder_limit_days': 'reorder_limit_days'
        }
        
        for client_field, db_field in field_mapping.items():
            if client_field in customer_data and customer_data[client_field] is not None:
                update_fields.append(f"{db_field} = %s")
                
                # 处理reorder_limit_days的类型转换
                if client_field == 'reorder_limit_days':
                    try:
                        value = int(customer_data[client_field]) if customer_data[client_field] is not None else 0
                    except (ValueError, TypeError):
                        value = 0
                    update_values.append(value)
                else:
                    update_values.append(customer_data[client_field])
        
        # 处理密码更新
        password_changed = False
        if 'password' in customer_data and customer_data['password']:
            import bcrypt
            salt = bcrypt.gensalt()
            password_hash = bcrypt.hashpw(customer_data['password'].encode('utf-8'), salt).decode('utf-8')
            update_fields.append("password = %s")
            update_values.append(password_hash)
            password_changed = True
        
        # 如果没有字段需要更新，检查是否需要更新LINE用户和群组
        line_users_changed = 'line_users' in customer_data
        line_groups_changed = 'line_groups' in customer_data
        
        # 如果只有密码变更，也认为是有更新的
        if not update_fields and not line_users_changed and not line_groups_changed and not password_changed:
            return True, None  # 没有任何更新
        
        # 如果有字段需要更新，执行更新
        if update_fields:
            update_fields.append("updated_at = NOW()")
            
            update_values.append(customer_id)
            update_query = f"""
                UPDATE customers 
                SET {', '.join(update_fields)}
                WHERE id = %s
            """
            
            cursor.execute(update_query, tuple(update_values))
        
        # 处理LINE用户更新
        if line_users_changed:
            new_line_users = customer_data.get('line_users', [])
            
            # 清除旧的LINE用户关联
            cursor.execute("DELETE FROM line_users WHERE customer_id = %s", (customer_id,))
            
            # 添加新的LINE用户
            for user in new_line_users:
                line_user_id = user.get('line_user_id')
                user_name = user.get('user_name')
                if line_user_id and user_name:
                    # 检查此LINE用户ID是否已绑定到其他客户
                    cursor.execute(
                        "SELECT customer_id FROM line_users WHERE line_user_id = %s",
                        (line_user_id,)
                    )
                    existing = cursor.fetchone()
                    if existing and existing[0] != customer_id:
                        continue  # 跳过已绑定到其他客户的LINE用户
                    
                    # 插入LINE用户
                    cursor.execute(
                        """
                        INSERT INTO line_users 
                        (line_user_id, user_name, customer_id)
                        VALUES (%s, %s, %s)
                        """,
                        (line_user_id, user_name, customer_id)
                    )
        
        # 处理LINE群组更新
        if line_groups_changed:
            new_line_groups = customer_data.get('line_groups', [])
            
            # 清除旧的LINE群组关联
            cursor.execute("DELETE FROM line_groups WHERE customer_id = %s", (customer_id,))
            
            # 添加新的LINE群组
            for group in new_line_groups:
                line_group_id = group.get('line_group_id')
                group_name = group.get('group_name')
                if line_group_id and group_name:
                    # 检查此LINE群组ID是否已绑定到其他客户
                    cursor.execute(
                        "SELECT customer_id FROM line_groups WHERE line_group_id = %s",
                        (line_group_id,)
                    )
                    existing = cursor.fetchone()
                    if existing and existing[0] != customer_id:
                        continue  # 跳过已绑定到其他客户的LINE群组
                    
                    # 插入LINE群组
                    cursor.execute(
                        """
                        INSERT INTO line_groups 
                        (line_group_id, group_name, customer_id)
                        VALUES (%s, %s, %s)
                        """,
                        (line_group_id, group_name, customer_id)
                    )
        
        # 获取更新后的客户数据用于记录变更
        cursor.execute(
            """
            SELECT id, username, company_name, contact_name, phone, email, 
                   address, viewable_products, remark, created_at, 
                   updated_at, status, reorder_limit_days
            FROM customers
            WHERE id = %s
            """,
            (customer_id,)
        )
        
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        new_data = dict(zip(columns, row))
        
        # 转换contact_name为contact_person以保持一致性
        if 'contact_name' in new_data:
            new_data['contact_person'] = new_data['contact_name']
        
        # 获取新的LINE用户列表
        cursor.execute(
            """
            SELECT id, line_user_id, user_name
            FROM line_users
            WHERE customer_id = %s
            """,
            (customer_id,)
        )
        new_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
        new_data['line_users'] = new_line_users
        
        # 获取新的LINE群组列表
        cursor.execute(
            """
            SELECT id, line_group_id, group_name
            FROM line_groups
            WHERE customer_id = %s
            """,
            (customer_id,)
        )
        new_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
        new_data['line_groups'] = new_line_groups
        
        # 为向后兼容，添加空的line_account字段
        new_data['line_account'] = ''
        
        # 格式化日期
        if 'created_at' in new_data and new_data['created_at']:
            new_data['created_at'] = new_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        if 'updated_at' in new_data and new_data['updated_at']:
            new_data['updated_at'] = new_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        # 添加密码变更标记
        if password_changed:
            new_data['password_changed'] = True
            # 確保即使沒有其他變更也記錄
            if not update_fields and not line_users_changed and not line_groups_changed:
                print(f"Only password changed for customer_id: {customer_id}")
                # 添加一個無意義的更新來觸發數據庫更新
                update_fields.append("updated_at = NOW()")
                update_values.append(customer_id)
                update_query = f"""
                    UPDATE customers 
                    SET updated_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(update_query, tuple([customer_id]))
        
        # 记录日志
        try:
            # 获取当前登录的管理员信息
            admin_id = session.get('admin_id')
            
            # 初始化日誌服務並記錄操作
            from backend.services.log_service_registry import LogServiceRegistry
            log_service = LogServiceRegistry.get_service(conn, 'customers')
            log_service.log_operation(
                table_name='customers',
                operation_type='修改',
                record_id=customer_id,
                old_data=old_data,
                new_data=new_data,
                performed_by=admin_id,
                user_type='管理員'
            )
        except Exception as log_error:
            print(f"Error logging customer update: {str(log_error)}")
        
        return True, None
        
    except Exception as e:
        print(f"Error in _process_update: {str(e)}")
        return False, str(e)

@customer_bp.route('/line/unbind-user', methods=['POST'])
def unbind_line_user():
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        user_id = data.get('user_id')
        
        if not customer_id or not user_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # 查询LINE用户信息
            cursor.execute("""
                SELECT id, customer_id, line_user_id, user_name
                FROM line_users 
                WHERE id = %s AND customer_id = %s
            """, (user_id, customer_id))
            
            line_user = cursor.fetchone()
            if not line_user:
                return jsonify({
                    "status": "error",
                    "message": "找不到LINE用戶資料或無權操作"
                }), 404
                
            # 查询客户当前信息（用于记录变更日志）
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address,
                       viewable_products, remark, reorder_limit_days
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            old_data_row = cursor.fetchone()
            if not old_data_row:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404
                
            old_customer_data = dict(old_data_row)
            # 轉換contact_name為contact_person以保持一致性
            if 'contact_name' in old_customer_data:
                old_customer_data['contact_person'] = old_customer_data['contact_name']
                
            # 获取客户的所有LINE用户
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_users'] = old_line_users
            
            # 获取客户的所有LINE群组
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_groups'] = old_line_groups
            
            # 为向后兼容，添加空的line_account字段
            old_customer_data['line_account'] = ''
            
            # 删除LINE用户
            cursor.execute("""
                DELETE FROM line_users 
                WHERE id = %s AND customer_id = %s
                RETURNING id;
            """, (user_id, customer_id))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "解綁失敗，找不到LINE用戶資料"
                }), 404

            conn.commit()
            
            # 准备新客户数据用于日志记录
            new_customer_data = old_customer_data.copy()
            # 更新LINE用户列表，移除已解绑的用户
            removed_user = next((u for u in old_line_users if u['id'] == int(user_id)), None)
            new_customer_data['line_users'] = [u for u in old_line_users if u['id'] != int(user_id)]
            
            # 添加詳細的變更信息
            if removed_user:
                changes = {
                    'line_users': {
                        'before': [{'user_name': user.get('user_name', '未知用戶')} for user in old_line_users],
                        'after': [{'user_name': user.get('user_name', '未知用戶')} for user in new_customer_data['line_users']]
                    }
                }
                # LINE帳號變更
                if removed_user.get('user_name'):
                    changes['line_account'] = {
                        'before': removed_user.get('user_name', '未知用戶'),
                        'after': ''
                    }
                new_customer_data['line_changes'] = changes
            
            try:
                # 记录日志
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 初始化日誌服務並記錄操作
                log_service = LogServiceRegistry.get_service(conn, 'customers')
                log_service.log_operation(
                    table_name='customers',
                    operation_type='修改',
                    record_id=customer_id,
                    old_data=old_customer_data,
                    new_data=new_customer_data,
                    performed_by=customer_id,
                    user_type='客戶'
                )
            except Exception as log_error:
                # 日誌記錄失敗不影響主要功能
                print(f"Error logging LINE user unbind operation: {str(log_error)}")
            
            return jsonify({
                "status": "success",
                "message": "LINE用戶解除綁定成功"
            })

    except Exception as e:
        print(f"Error in unbind_line_user: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/line/unbind-group', methods=['POST'])
def unbind_line_group():
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        group_id = data.get('group_id')
        
        if not customer_id or not group_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # 查询LINE群组信息
            cursor.execute("""
                SELECT id, customer_id, line_group_id, group_name
                FROM line_groups 
                WHERE id = %s AND customer_id = %s
            """, (group_id, customer_id))
            
            line_group = cursor.fetchone()
            if not line_group:
                return jsonify({
                    "status": "error",
                    "message": "找不到LINE群組資料或無權操作"
                }), 404
                
            # 查询客户当前信息（用于记录变更日志）
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address,
                       viewable_products, remark, reorder_limit_days
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            old_data_row = cursor.fetchone()
            if not old_data_row:
                return jsonify({
                    "status": "error",
                    "message": "找不到客戶資料"
                }), 404
            
            old_customer_data = dict(old_data_row)
            # 轉換contact_name為contact_person以保持一致性
            if 'contact_name' in old_customer_data:
                old_customer_data['contact_person'] = old_customer_data['contact_name']
            
            # 获取客户的所有LINE用户
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_users'] = old_line_users
            
            # 获取客户的所有LINE群组
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_groups'] = old_line_groups
            
            # 为向后兼容，添加空的line_account字段
            old_customer_data['line_account'] = ''
            
            # 删除LINE群组
            cursor.execute("""
                DELETE FROM line_groups 
                WHERE id = %s AND customer_id = %s
                RETURNING id;
            """, (group_id, customer_id))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "解綁失敗，找不到LINE群組資料"
                }), 404

            conn.commit()
            
            # 准备新客户数据用于日志记录
            new_customer_data = old_customer_data.copy()
            # 更新LINE群组列表，移除已解绑的群组
            removed_group = next((g for g in old_line_groups if g['id'] == int(group_id)), None)
            new_customer_data['line_groups'] = [g for g in old_line_groups if g['id'] != int(group_id)]
            
            # 添加詳細的變更信息
            if removed_group:
                changes = {
                    'line_groups': {
                        'before': [{'group_name': group.get('group_name', '未命名群組')} for group in old_line_groups],
                        'after': [{'group_name': group.get('group_name', '未命名群組')} for group in new_customer_data['line_groups']]
                    }
                }
                # LINE帳號變更
                if removed_group.get('group_name'):
                    changes['line_account'] = {
                        'before': removed_group.get('group_name', '未命名群組'),
                        'after': ''
                    }
                new_customer_data['line_changes'] = changes
            
            try:
                # 记录日志
                from backend.services.log_service_registry import LogServiceRegistry
                
                # 初始化日誌服務並記錄操作
                log_service = LogServiceRegistry.get_service(conn, 'customers')
                log_service.log_operation(
                    table_name='customers',
                    operation_type='修改',
                    record_id=customer_id,
                    old_data=old_customer_data,
                    new_data=new_customer_data,
                    performed_by=customer_id,
                    user_type='客戶'
                )
            except Exception as log_error:
                # 日誌記錄失敗不影響主要功能
                print(f"Error logging LINE group unbind operation: {str(log_error)}")
            
            return jsonify({
                "status": "success",
                "message": "LINE群組解除綁定成功"
            })

    except Exception as e:
        print(f"Error in unbind_line_group: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/line/bind', methods=['POST'])
def bind_line():
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        line_user_id = data.get('line_user_id')
        line_group_id = data.get('line_group_id')
        bind_type = data.get('bind_type', 'user')  # 默认绑定类型为个人用户
        
        # 如果是LINE LIFF应用发来的请求，line_user_id是必须的
        # 如果是群组绑定请求，line_group_id是必须的
        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "客戶ID不能為空"
                }), 400
            
        if not line_user_id and not line_group_id:
            return jsonify({
                "status": "error",
                "message": "LINE ID不能為空"
            }), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 检查客户是否存在
            cursor.execute("""
                SELECT id FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            if not cursor.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "客戶不存在或已被停用"
                }), 404
            
            # 准备日志记录的旧数据
            cursor.execute("""
                SELECT id, username, company_name, contact_name, phone, email, address,
                       viewable_products, remark, reorder_limit_days
                FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            old_data_row = cursor.fetchone()
            old_customer_data = dict(zip(['id', 'username', 'company_name', 'contact_name', 
                                         'phone', 'email', 'address', 
                                         'viewable_products', 'remark', 'reorder_limit_days'], 
                                         old_data_row))
            
            # 获取现有的LINE用户列表
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_users'] = old_line_users
            
            # 获取现有的LINE群组列表
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            old_customer_data['line_groups'] = old_line_groups
            
            # 为向后兼容，添加空的line_account字段
            old_customer_data['line_account'] = ''
            
            # 处理绑定请求
            if line_user_id:
                # 检查该LINE用户是否已绑定到其他客户
                cursor.execute("""
                    SELECT c.id FROM line_users lu
                    JOIN customers c ON lu.customer_id = c.id
                    WHERE lu.line_user_id = %s 
                    AND lu.customer_id != %s 
                    AND c.status = 'active'
                """, (line_user_id, customer_id))
                
                if cursor.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "此LINE帳號已被其他客戶綁定"
                    }), 400
                
                # 检查LINE用户是否已绑定到当前客户
                cursor.execute("""
                    SELECT id FROM line_users 
                    WHERE line_user_id = %s AND customer_id = %s
                """, (line_user_id, customer_id))
                
                existing_user = cursor.fetchone()
                if existing_user:
                    # 如果已绑定，更新用户名
                    cursor.execute("""
                        UPDATE line_users 
                        SET user_name = %s, updated_at = NOW()
                        WHERE line_user_id = %s
                    """, (data.get('user_name', ''), line_user_id))
                else:
                    # 绑定LINE用户（新增）
                    cursor.execute("""
                        INSERT INTO line_users (
                            customer_id, line_user_id, user_name, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, NOW(), NOW()
                        )
                    """, (customer_id, line_user_id, data.get('user_name', '')))
            
            if line_group_id:
                # 检查该LINE群组是否已绑定到其他客户
                cursor.execute("""
                    SELECT c.id FROM line_groups lg
                    JOIN customers c ON lg.customer_id = c.id
                    WHERE lg.line_group_id = %s 
                    AND lg.customer_id != %s 
                    AND c.status = 'active'
                """, (line_group_id, customer_id))
                
                if cursor.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "此LINE群組已被其他客戶綁定"
                    }), 400
                
                # 检查LINE群组是否已绑定到当前客户
                cursor.execute("""
                    SELECT id FROM line_groups 
                    WHERE line_group_id = %s AND customer_id = %s
                """, (line_group_id, customer_id))
                
                existing_group = cursor.fetchone()
                if existing_group:
                    # 如果已绑定，更新群组名
                    cursor.execute("""
                        UPDATE line_groups 
                        SET group_name = %s, updated_at = NOW()
                        WHERE line_group_id = %s
                    """, (data.get('group_name', ''), line_group_id))
                else:
                    # 绑定LINE群组（新增）
                    cursor.execute("""
                        INSERT INTO line_groups (
                            customer_id, line_group_id, group_name, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, NOW(), NOW()
                        )
                    """, (customer_id, line_group_id, data.get('group_name', '')))
            
            # 获取更新后的LINE用户列表
            cursor.execute("""
                SELECT id, line_user_id, user_name
                FROM line_users
                WHERE customer_id = %s
            """, (customer_id,))
            new_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
            
            # 获取更新后的LINE群组列表
            cursor.execute("""
                SELECT id, line_group_id, group_name
                FROM line_groups
                WHERE customer_id = %s
            """, (customer_id,))
            new_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
            
            conn.commit()
            
            # 准备新客户数据用于日志记录
            new_customer_data = old_customer_data.copy()
            new_customer_data['line_users'] = new_line_users
            new_customer_data['line_groups'] = new_line_groups
            
            # 創建變更詳情
            changes = {}
            
            # 檢查LINE用戶變更
            old_users_set = {user.get('line_user_id') for user in old_line_users if user.get('line_user_id')}
            new_users_set = {user.get('line_user_id') for user in new_line_users if user.get('line_user_id')}
            
            if old_users_set != new_users_set:
                changes['line_users'] = {
                    'before': [{'user_name': user.get('user_name', '未知用戶')} for user in old_line_users],
                    'after': [{'user_name': user.get('user_name', '未知用戶')} for user in new_line_users]
                }
                
                # 檢查新增用戶
                added_users = new_users_set - old_users_set
                if added_users:
                    # 為了向後兼容，添加line_account變更
                    added_user_id = list(added_users)[0]  # 取第一個新增用戶
                    added_user = next((u for u in new_line_users if u.get('line_user_id') == added_user_id), None)
                    if added_user:
                        changes['line_account'] = {
                            'before': '',
                            'after': added_user.get('user_name', '未知用戶')
                        }
            
            # 檢查LINE群組變更
            old_groups_set = {group.get('line_group_id') for group in old_line_groups if group.get('line_group_id')}
            new_groups_set = {group.get('line_group_id') for group in new_line_groups if group.get('line_group_id')}
            
            if old_groups_set != new_groups_set:
                changes['line_groups'] = {
                    'before': [{'group_name': group.get('group_name', '未命名群組')} for group in old_line_groups],
                    'after': [{'group_name': group.get('group_name', '未命名群組')} for group in new_line_groups]
                }
                
                # 檢查新增群組
                added_groups = new_groups_set - old_groups_set
                if added_groups and 'line_account' not in changes:  # 如果還沒有設置line_account
                    added_group_id = list(added_groups)[0]  # 取第一個新增群組
                    added_group = next((g for g in new_line_groups if g.get('line_group_id') == added_group_id), None)
                    if added_group:
                        changes['line_account'] = {
                            'before': '',
                            'after': added_group.get('group_name', '未命名群組')
                        }
            
            # 添加變更詳情到新數據
            if changes:
                new_customer_data['line_changes'] = changes
            
            # 如果有變更，記錄在客戶表的日誌中
            if changes:
                try:
                    # 獲取操作者ID
                    admin_id = session.get('admin_id')
                    user_type = '管理員' if admin_id else '客戶'
                    performer_id = admin_id or new_customer_data.get('id')
                    
                    # 添加變更信息到新客戶數據
                    new_customer_with_changes = new_customer_data.copy()
                    new_customer_with_changes['line_changes'] = changes
                    
                    # 初始化日誌服務並記錄操作
                    from backend.services.log_service_registry import LogServiceRegistry
                    log_service = LogServiceRegistry.get_service(conn, 'customers')
                    
                    log_service.log_operation(
                        table_name='customers',
                        operation_type='修改',
                        record_id=customer_id,
                        old_data=old_customer_data,
                        new_data=new_customer_with_changes,
                        performed_by=performer_id,
                        user_type=user_type
                    )
                except Exception as log_error:
                    print(f"Error logging LINE account changes: {str(log_error)}")
            
            return jsonify({
                "status": "success",
                "message": "LINE帳號綁定成功",
                "bind_type": "user" if line_user_id else "group"
            })
            
    except Exception as e:
        print(f"Error in bind_line: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@customer_bp.route('/line/generate-bind-url', methods=['POST'])
def generate_bind_url():
    """生成LINE綁定URL"""
    try:
        # 打印請求信息以便調試
        print("Customer routes - Generate bind URL called")
        print(f"Session: {session}")
        print(f"Request headers: {dict(request.headers)}")
        
        data = request.get_json()
        customer_id = data.get('customer_id')
        bind_type = data.get('bind_type', 'user')  # 默认为用户账号绑定
        
        print(f"Request data: customer_id={customer_id}, bind_type={bind_type}")
        
        if not customer_id:
            return jsonify({"status": "error", "message": "缺少必要參數"}), 400
            
        # 验证客户是否存在
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT id FROM customers WHERE id = %s AND status = 'active'", 
                (customer_id,)
            )
            
            if not cursor.fetchone():
                return jsonify({"status": "error", "message": "客戶不存在或已停用"}), 404
            
            # 使用正確的環境變數 - 檢查多個可能的名稱
            liff_id = os.environ.get('LINE_LIFF_ID') or os.environ.get('LIFF_ID')
            print(f"LIFF ID from env: {liff_id}")
            
            if not liff_id:
                print("ERROR: LIFF ID not found in environment variables")
                return jsonify({"status": "error", "message": "LIFF尚未配置"}), 500
                
            # 直接使用LIFF ID構建URL
            line_login_url = (
                f"https://liff.line.me/{liff_id}"
                f"?customer_id={quote(str(customer_id))}"
                f"&type={quote(bind_type)}"
            )
            
            print(f"Generated LIFF URL: {line_login_url}")
            
            return jsonify({
                "status": "success",
                "data": {
                    "bind_url": line_login_url,
                    "url": line_login_url  # 兼容性保留
                }
            })
    
    except Exception as e:
        print(f"Error generating LINE bind URL: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def _process_line_account_changes(old_customer, new_customer, cursor, conn):
    """處理 LINE 賬戶變更邏輯"""
    try:
        # 檢查 line_users 變更
        old_line_users = old_customer.get('line_users', [])
        new_line_users = new_customer.get('line_users', [])
        
        changes = {}
        has_changes = False
        
        # 檢查LINE用戶是否有變更
        old_users_set = {user.get('line_user_id') for user in old_line_users if user.get('line_user_id')}
        new_users_set = {user.get('line_user_id') for user in new_line_users if user.get('line_user_id')}
        
        if old_users_set != new_users_set:
            has_changes = True
            # 簡化記錄，只包含用戶名稱
            changes['line_users'] = {
                'before': [{'user_name': user.get('user_name', '未知用戶')} for user in old_line_users],
                'after': [{'user_name': user.get('user_name', '未知用戶')} for user in new_line_users]
            }
            
            # 檢查新增用戶
            added_users = new_users_set - old_users_set
            if added_users:
                # 為了向後兼容，添加line_account變更
                added_user_id = list(added_users)[0]  # 取第一個新增用戶
                added_user = next((u for u in new_line_users if u.get('line_user_id') == added_user_id), None)
                if added_user:
                    changes['line_account'] = {
                        'before': '',
                        'after': added_user.get('user_name', '未知用戶')
                    }
        
        # 檢查 line_groups 變更
        old_line_groups = old_customer.get('line_groups', [])
        new_line_groups = new_customer.get('line_groups', [])
        
        # 檢查LINE群組是否有變更
        old_groups_set = {group.get('line_group_id') for group in old_line_groups if group.get('line_group_id')}
        new_groups_set = {group.get('line_group_id') for group in new_line_groups if group.get('line_group_id')}
        
        if old_groups_set != new_groups_set:
            has_changes = True
            # 簡化記錄，只包含群組名稱
            changes['line_groups'] = {
                'before': [{'group_name': group.get('group_name', '未命名群組')} for group in old_line_groups],
                'after': [{'group_name': group.get('group_name', '未命名群組')} for group in new_line_groups]
            }
            
            # 檢查新增群組
            added_groups = new_groups_set - old_groups_set
            if added_groups and 'line_account' not in changes:  # 如果還沒有設置line_account
                added_group_id = list(added_groups)[0]  # 取第一個新增群組
                added_group = next((g for g in new_line_groups if g.get('line_group_id') == added_group_id), None)
                if added_group:
                    changes['line_account'] = {
                        'before': '',
                        'after': added_group.get('group_name', '未命名群組')
                    }
        
        # 如果有變更，記錄在客戶表的日誌中
        if has_changes:
            try:
                # 獲取操作者ID
                admin_id = session.get('admin_id')
                user_type = '管理員' if admin_id else '客戶'
                performer_id = admin_id or new_customer.get('id')
                
                # 添加變更信息到新客戶數據
                new_customer_with_changes = new_customer.copy()
                new_customer_with_changes['line_changes'] = changes
                
                # 初始化日誌服務並記錄操作
                from backend.services.log_service_registry import LogServiceRegistry
                log_service = LogServiceRegistry.get_service(conn, 'customers')
                
                log_service.log_operation(
                    table_name='customers',
                    operation_type='修改',
                    record_id=new_customer.get('id'),
                    old_data=old_customer,
                    new_data=new_customer_with_changes,
                    performed_by=performer_id,
                    user_type=user_type
                )
            except Exception as log_error:
                print(f"Error logging LINE account changes: {str(log_error)}")
        
        return True
    except Exception as e:
        print(f"Error processing LINE account changes: {str(e)}")
        return False

