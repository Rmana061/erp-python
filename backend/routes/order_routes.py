from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from datetime import datetime
from backend.utils.email_utils import EmailSender
import threading
from backend.services.log_service import LogService
from functools import wraps
import requests
import json

order_bp = Blueprint('order', __name__, url_prefix='/api')

# 通用的郵件發送函數
def send_email_async(email_func, recipient_email, order_data):
    try:
        email_sender = EmailSender()
        thread = threading.Thread(
            target=email_func,
            args=(email_sender, recipient_email, order_data)
        )
        thread.start()
    except Exception as e:
        print(f"發送郵件時出錯: {str(e)}")

# 常量定義
ORDER_DETAIL_SQL = """
    SELECT 
        o.order_number,
        o.created_at as order_date,
        o.updated_at as confirm_date,
        c.email as customer_email,
        json_agg(json_build_object(
            'product_name', p.name,
            'quantity', od.product_quantity,
            'unit', od.product_unit,
            'shipping_date', od.shipping_date,
            'remark', od.remark,
            'supplier_note', od.supplier_note,
            'order_status', od.order_status
        )) as items
    FROM orders o
    JOIN order_details od ON o.id = od.order_id
    JOIN products p ON od.product_id = p.id
    JOIN customers c ON o.customer_id = c.id
    WHERE o.order_number = %s
    GROUP BY o.order_number, o.created_at, o.updated_at, c.email
"""

# 通用的錯誤響應函數
def error_response(message, status_code=400):
    return jsonify({
        'status': 'error',
        'message': message
    }), status_code

# 通用的成功響應函數
def success_response(data=None, message=None):
    response = {'status': 'success'}
    if message:
        response['message'] = message
    if data:
        response['data'] = data
    return jsonify(response)

# 格式化日期時間
def format_datetime(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None

def format_date(dt):
    return dt.strftime('%Y-%m-%d') if dt else None

def send_order_email(customer_email, order_data):
    try:
        email_sender = EmailSender()
        email_sender.send_order_confirmation(customer_email, order_data)
    except Exception as e:
        print(f"發送郵件時出錯: {str(e)}")

def send_cancel_email(customer_email, order_data):
    email_sender = EmailSender()
    email_sender.send_order_cancellation(customer_email, order_data)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_id'):
            return jsonify({"status": "error", "message": "需要管理員權限"}), 401
        return f(*args, **kwargs)
    return decorated_function

def log_operation(table_name, operation_type, record_id, old_data, new_data, performed_by, user_type):
    """记录操作日志的辅助函数"""
    try:
        with get_db_connection() as conn:
            log_service = LogService(conn)
            print(f"Logging operation: {operation_type} on {table_name} with ID {record_id}")
            print(f"Old data: {json.dumps(old_data, ensure_ascii=False) if old_data else None}")
            print(f"New data: {json.dumps(new_data, ensure_ascii=False) if new_data else None}")
            print(f"Performed by: {performed_by}, User type: {user_type}")
            
            result = log_service.log_operation(
                table_name=table_name,
                operation_type=operation_type,
                record_id=record_id,
                old_data=old_data,
                new_data=new_data,
                performed_by=performed_by,
                user_type=user_type
            )
            
            if result:
                print(f"Successfully logged {operation_type} operation")
                conn.commit()
            else:
                print(f"Failed to log {operation_type} operation")
                
            return result
    except Exception as e:
        print(f"Error logging operation: {str(e)}")
        return False

@order_bp.route('/orders/create', methods=['POST'])
def create_order():
    try:
        data = request.json
        print(f"Received order data: {json.dumps(data, ensure_ascii=False, indent=2)}")
        customer_id = data.get('customer_id')
        
        if not data or 'order_number' not in data or 'customer_id' not in data or 'products' not in data:
            return error_response('缺少必要參數')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查訂單編號是否已存在
            cursor.execute("""
                SELECT id FROM orders WHERE order_number = %s
            """, (data['order_number'],))
            
            if cursor.fetchone():
                return error_response('訂單編號已存在')

            # 創建訂單
            cursor.execute("""
                INSERT INTO orders (
                    order_number, customer_id,
                    order_confirmed, order_shipped,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, false, false, NOW(), NOW()
                ) RETURNING id
            """, (
                data['order_number'],
                data['customer_id']
            ))
            
            order_id = cursor.fetchone()[0]
            
            # 創建訂單項目
            for product in data['products']:
                cursor.execute("""
                    INSERT INTO order_details (
                        order_id, product_id, product_quantity,
                        product_unit, order_status, shipping_date,
                        remark, supplier_note, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    order_id,
                    product['product_id'],
                    product['product_quantity'],
                    product['product_unit'],
                    product['order_status'],
                    product['shipping_date'],
                    product.get('remark', ''),
                    product.get('supplier_note', ''),
                ))
            
            # 獲取訂單詳細信息用於發送郵件
            cursor.execute(ORDER_DETAIL_SQL, (data['order_number'],))
            order_info = cursor.fetchone()
            
            if order_info:
                # 準備郵件數據
                email_data = {
                    'order_number': order_info[0],
                    'order_date': format_datetime(order_info[1]),
                    'items': order_info[4]
                }
                
                # 在新線程中發送郵件
                customer_email = order_info[3]
                threading.Thread(
                    target=send_order_email,
                    args=(customer_email, email_data)
                ).start()
            
            # 记录日志
            cursor.execute("""
                SELECT p.name, od.product_quantity, od.shipping_date, od.supplier_note, od.remark
                FROM order_details od
                JOIN products p ON od.product_id = p.id
                WHERE od.order_id = %s
            """, (order_id,))
            order_details = cursor.fetchall()

            products_info = []
            for detail in order_details:
                product_name, quantity, shipping_date, supplier_note, remark = detail
                shipping_date_str = shipping_date.strftime('%Y-%m-%d') if shipping_date else '待確認'
                supplier_note_str = supplier_note if supplier_note else '-'
                remark_str = remark if remark else '-'
                products_info.append({
                    'name': product_name,
                    'quantity': str(quantity),
                    'shipping_date': shipping_date_str,
                    'supplier_note': supplier_note_str,
                    'remark': remark_str
                })

            # 將消息轉換為 JSON 字符串
            message = {
                'order_number': data['order_number'],
                'status': '待確認',
                'products': products_info
            }

            log_operation(
                table_name='orders',
                operation_type='新增',
                record_id=order_id,
                old_data=None,
                new_data={
                    'message': json.dumps(message, ensure_ascii=False)  # 轉換為 JSON 字符串
                },
                performed_by=customer_id,
                user_type='客戶'
            )
            
            conn.commit()
            return success_response(message='訂單創建成功')
            
    except Exception as e:
        print(f"Error in create_order: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/list', methods=['POST'])
def get_orders():
    try:
        data = request.json
        if not data or 'customer_id' not in data:
            return error_response('缺少客戶ID')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查詢訂單和訂單詳情數據
            sql = """
                SELECT 
                    o.id as order_id,
                    o.order_number,
                    o.customer_id,
                    o.created_at as order_created_at,
                    od.id as detail_id,
                    od.product_id,
                    p.name as product_name,
                    od.product_quantity,
                    od.product_unit,
                    od.order_status,
                    od.shipping_date,
                    od.remark,
                    od.supplier_note,
                    od.created_at as detail_created_at
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN products p ON od.product_id = p.id
                WHERE o.customer_id = %s
                ORDER BY o.created_at DESC, od.created_at ASC;
            """
            
            cursor.execute(sql, (data['customer_id'],))
            
            # 獲取列名
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 重組數據結構
            orders = {}
            for row in rows:
                order_id = row['order_id']
                if order_id not in orders:
                    orders[order_id] = {
                        'order_id': row['order_id'],
                        'order_number': row['order_number'],
                        'created_at': format_datetime(row['order_created_at']),
                        'products': []
                    }
                
                orders[order_id]['products'].append({
                    'id': row['detail_id'],
                    'product_id': row['product_id'],
                    'product_name': row['product_name'],
                    'product_quantity': row['product_quantity'],
                    'product_unit': row['product_unit'],
                    'order_status': row['order_status'],
                    'shipping_date': format_date(row['shipping_date']),
                    'remark': row['remark'] or '',
                    'supplier_note': row['supplier_note'] or ''
                })
            
            return success_response(data=list(orders.values()))
            
    except Exception as e:
        print(f"Error in get_orders: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/cancel', methods=['POST'])
def cancel_order():
    try:
        data = request.json
        if not data or 'order_number' not in data:
            return error_response('缺少訂單編號')

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 獲取訂單和客戶信息
            cursor.execute("""
                SELECT 
                    o.id as order_id,
                    o.order_number,
                    o.customer_id,
                    c.email as customer_email,
                    json_agg(json_build_object(
                        'product_name', p.name,
                        'name', p.name,
                        'quantity', od.product_quantity,
                        'unit', od.product_unit,
                        'shipping_date', COALESCE(to_char(od.shipping_date, 'YYYY-MM-DD'), '待確認'),
                        'remark', COALESCE(od.remark, '-')
                    )) as products
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN products p ON od.product_id = p.id
                JOIN customers c ON o.customer_id = c.id
                WHERE o.order_number = %s
                GROUP BY o.id, o.order_number, o.customer_id, c.email
            """, (data['order_number'],))
            
            order_info = cursor.fetchone()
            if not order_info:
                return error_response('找不到該訂單', 404)

            # 檢查所有產品是否都是待確認狀態
            cursor.execute("""
                SELECT order_status 
                FROM order_details od
                JOIN orders o ON od.order_id = o.id
                WHERE o.order_number = %s
            """, (data['order_number'],))
            
            statuses = [row[0] for row in cursor.fetchall()]
            if not all(status == '待確認' for status in statuses):
                return error_response('只有待確認狀態的訂單可以取消', 400)

            # 準備日誌數據
            message = {
                'order_number': order_info[1],
                'status': '待確認',
                'products': order_info[4]
            }
            
            old_data = {
                'message': json.dumps(message, ensure_ascii=False)
            }

            # 準備郵件數據
            email_data = {
                'order_number': order_info[1],
                'cancel_date': format_datetime(datetime.now()),
                'items': order_info[4]
            }
            
            customer_email = order_info[3]
            customer_id = order_info[2]  # 获取客户ID

            # 刪除訂單詳情和主訂單
            cursor.execute("""
                WITH deleted_details AS (
                    DELETE FROM order_details
                    USING orders
                    WHERE orders.id = order_details.order_id
                    AND orders.order_number = %s
                    RETURNING 1
                )
                DELETE FROM orders
                WHERE order_number = %s
                RETURNING id;
            """, (data['order_number'], data['order_number']))

            deleted_order_id = cursor.fetchone()
            if not deleted_order_id:
                return error_response('訂單刪除失敗', 400)

            # 記錄日誌 - 使用客户ID作为performed_by
            log_operation(
                table_name='orders',
                operation_type='刪除',
                record_id=order_info[0],
                old_data=old_data,
                new_data=None,
                performed_by=customer_id,  # 使用客户ID而不是session中的customer_id
                user_type='客戶'
            )

            # 發送取消訂單郵件通知
            threading.Thread(
                target=send_cancel_email,
                args=(customer_email, email_data)
            ).start()

            conn.commit()
            return success_response(message='訂單已取消')

    except Exception as e:
        print(f"Error in cancel_order: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/today', methods=['POST'])
def get_today_orders():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查詢今日訂單
            sql = """
                SELECT 
                    o.id as order_id,
                    o.order_number,
                    o.created_at as order_date,
                    c.company_name as customer_name,
                    od.id as detail_id,
                    p.name as product_name,
                    od.product_quantity,
                    od.product_unit,
                    od.order_status,
                    od.shipping_date,
                    od.remark,
                    od.supplier_note
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN customers c ON o.customer_id = c.id
                JOIN products p ON od.product_id = p.id
                WHERE DATE(o.created_at) = CURRENT_DATE
                ORDER BY o.created_at DESC, od.id ASC;
            """
            
            cursor.execute(sql)
            
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 重組數據結構
            orders = []
            for row in rows:
                orders.append({
                    'id': row['detail_id'],
                    'order_id': row['order_id'],
                    'date': format_datetime(row['order_date']),
                    'customer': row['customer_name'],
                    'item': row['product_name'],
                    'quantity': str(row['product_quantity']),
                    'unit': row['product_unit'],
                    'orderNumber': row['order_number'],
                    'shipping_date': format_date(row['shipping_date']),
                    'note': row['remark'] or '',
                    'supplier_note': row['supplier_note'] or '',
                    'status': row['order_status']
                })
            
            return success_response(data=orders)
            
    except Exception as e:
        print(f"Error in get_today_orders: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/update-status', methods=['POST'])
def update_order_status():
    """更新訂單狀態、數量和供應商備註"""
    try:
        data = request.get_json()
        print(f"Received data: {data}")
        
        # 驗證管理員身份
        admin_id = session.get('admin_id')
        if not admin_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                try:
                    admin_id = int(auth_header.split(' ')[1])
                except (IndexError, ValueError):
                    return error_response('未授權的訪問', 401)
            else:
                return error_response('未授權的訪問', 401)

        detail_id = data.get('order_id')
        status = data.get('status')
        shipping_date = data.get('shipping_date')
        supplier_note = data.get('supplier_note', '')
        quantity = data.get('quantity')  # 新增：獲取數量參數

        if not detail_id or not status:
            return error_response('缺少必要參數')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取原始訂單信息用於日誌記錄
            cursor.execute("""
                SELECT 
                    od.id,
                    od.order_id,
                    od.product_quantity,
                    od.order_status,
                    od.shipping_date,
                    od.supplier_note,
                    o.order_number,
                    p.name as product_name
                FROM order_details od
                JOIN orders o ON od.order_id = o.id
                JOIN products p ON od.product_id = p.id
                WHERE od.id = %s
            """, (detail_id,))
            
            result = cursor.fetchone()
            if not result:
                return error_response('訂單不存在')

            # 將查詢結果轉換為字典
            original_order = {
                'id': result[0],
                'order_id': result[1],
                'product_quantity': result[2],
                'order_status': result[3],
                'shipping_date': result[4],
                'supplier_note': result[5],
                'order_number': result[6],
                'product_name': result[7]
            }

            # 構建更新查詢
            update_query = """
                UPDATE order_details 
                SET order_status = %s,
                    shipping_date = %s,
                    supplier_note = %s,
                    updated_at = NOW()
            """
            params = [status, shipping_date, supplier_note]

            # 如果提供了數量，加入數量更新
            if quantity is not None:
                update_query += ", product_quantity = %s"
                params.append(quantity)

            update_query += " WHERE id = %s"
            params.append(detail_id)

            cursor.execute(update_query, params)

            # 準備日誌記錄
            old_message = f"訂單號:{original_order['order_number']}、產品:{original_order['product_name']}、數量:{original_order['product_quantity']}、狀態:{original_order['order_status']}、出貨日期:{original_order['shipping_date'] or '待確認'}、供應商備註:{original_order['supplier_note'] or '-'}"
            new_message = f"訂單號:{original_order['order_number']}、產品:{original_order['product_name']}、數量:{quantity or original_order['product_quantity']}、狀態:{status}、出貨日期:{shipping_date or '待確認'}、供應商備註:{supplier_note or '-'}"

            # 記錄操作日誌
            log_operation(
                table_name='orders',
                operation_type='修改',
                record_id=original_order['order_id'],
                old_data={'message': old_message},
                new_data={'message': new_message},
                performed_by=admin_id,
                user_type='管理員'
            )

            conn.commit()
            return success_response(message='訂單更新成功')

    except Exception as e:
        print(f"Error in update_order_status: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/pending', methods=['POST'])
def get_pending_orders():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查詢所有待確認狀態的訂單
            sql = """
                SELECT 
                    o.id,
                    o.order_number,
                    o.created_at as date,
                    c.company_name as customer,
                    od.id as detail_id,
                    p.name as item,
                    od.product_quantity as quantity,
                    od.product_unit as unit,
                    od.order_status as status,
                    od.shipping_date,
                    od.remark,
                    od.supplier_note
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN customers c ON o.customer_id = c.id
                JOIN products p ON od.product_id = p.id
                WHERE od.order_status = '待確認'
                ORDER BY o.created_at DESC;
            """
            
            cursor.execute(sql)
            
            # 獲取列名
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            
            # 处理日期格式
            for row in results:
                if row['date']:
                    row['date'] = row['date'].strftime('%Y-%m-%d %H:%M:%S')
                if row['shipping_date']:
                    row['shipping_date'] = row['shipping_date'].strftime('%Y-%m-%d')
            
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'data': results
            })
            
    except Exception as e:
        print(f"Error in get_pending_orders: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/all', methods=['POST'])
def get_all_orders():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 查詢所有訂單
            sql = """
                SELECT 
                    o.id,
                    o.order_number,
                    o.created_at as date,
                    c.company_name as customer,
                    od.id as detail_id,
                    p.name as item,
                    od.product_quantity as quantity,
                    od.product_unit as unit,
                    od.order_status as status,
                    od.shipping_date,
                    od.remark,
                    od.supplier_note
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                JOIN customers c ON o.customer_id = c.id
                JOIN products p ON od.product_id = p.id
                ORDER BY o.created_at DESC;
            """
            
            cursor.execute(sql)
            
            # 獲取列名
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            # 處理日期格式
            for row in results:
                if row['date']:
                    row['date'] = row['date'].strftime('%Y-%m-%d %H:%M:%S')
                if row['shipping_date']:
                    row['shipping_date'] = row['shipping_date'].strftime('%Y-%m-%d')
            
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'data': results
            })
            
    except Exception as e:
        print(f"Error in get_all_orders: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/update-confirmed', methods=['POST'])
def update_order_confirmed():
    try:
        data = request.json
        if not data or 'order_number' not in data:
            return error_response('缺少訂單編號')

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 獲取訂單詳細信息
            cursor.execute(ORDER_DETAIL_SQL, (data['order_number'],))
            order_info = cursor.fetchone()
            
            if not order_info:
                return error_response('找不到該訂單', 404)

            # 檢查訂單狀態
            statuses = [item['order_status'] for item in order_info[4]]
            all_confirmed_or_cancelled = all(status in ['已確認', '已取消'] for status in statuses)
            has_confirmed = any(status == '已確認' for status in statuses)
            
            if not all_confirmed_or_cancelled:
                return error_response('尚有產品未完成審核', 400)

            # 更新訂單確認狀態
            cursor.execute("""
                UPDATE orders 
                SET order_confirmed = true,
                    updated_at = NOW()
                WHERE order_number = %s
                RETURNING 1
            """, (data['order_number'],))

            if not cursor.fetchone():
                return error_response('訂單更新失敗', 400)

            conn.commit()

            # 只有當訂單中有已確認的產品時才發送確認郵件
            if has_confirmed:
                email_data = {
                    'order_number': order_info[0],
                    'confirm_date': format_datetime(order_info[2]),
                    'items': order_info[4]
                }
                
                threading.Thread(
                    target=lambda: EmailSender().send_order_approved(order_info[3], email_data)
                ).start()

            return success_response(message='訂單確認狀態已更新')

    except Exception as e:
        print(f"Error in update_order_confirmed: {str(e)}")
        return error_response(str(e), 500)

@order_bp.route('/orders/update-shipped', methods=['POST'])
def update_order_shipped():
    try:
        data = request.json
        if not data or 'order_number' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少訂單編號'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 檢查訂單所有產品狀態
            cursor.execute("""
                SELECT od.order_status 
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                WHERE o.order_number = %s
            """, (data['order_number'],))

            statuses = [row[0] for row in cursor.fetchall()]
            
            # 檢查是否所有已確認的產品都已出貨，已取消的產品不影響狀態
            all_processed = all(
                status in ['已出貨', '已取消'] 
                for status in statuses
            )
            
            if all_processed:
                # 更新訂單出貨狀態
                cursor.execute("""
                    UPDATE orders 
                    SET order_shipped = true,
                        updated_at = NOW()
                    WHERE order_number = %s
                """, (data['order_number'],))

                # 獲取訂單詳細信息用於發送郵件
                cursor.execute("""
                    SELECT 
                        o.order_number,
                        o.updated_at as shipped_date,
                        c.email as customer_email,
                        json_agg(json_build_object(
                            'product_name', p.name,
                            'quantity', od.product_quantity,
                            'unit', od.product_unit,
                            'shipping_date', od.shipping_date,
                            'remark', od.remark,
                            'supplier_note', od.supplier_note
                        )) as items
                    FROM orders o
                    JOIN order_details od ON o.id = od.order_id
                    JOIN products p ON od.product_id = p.id
                    JOIN customers c ON o.customer_id = c.id
                    WHERE o.order_number = %s
                    GROUP BY o.order_number, o.updated_at, c.email
                """, (data['order_number'],))

                order_info = cursor.fetchone()
                if order_info:
                    # 準備郵件數據
                    email_data = {
                        'order_number': order_info[0],
                        'confirm_date': order_info[1].strftime('%Y-%m-%d %H:%M:%S'),
                        'items': order_info[3]
                    }
                    
                    # 在新線程中發送郵件
                    customer_email = order_info[2]
                    email_sender = EmailSender()
                    threading.Thread(
                        target=email_sender.send_order_shipped,
                        args=(customer_email, email_data)
                    ).start()

                conn.commit()
                
                return jsonify({
                    'status': 'success',
                    'message': '訂單出貨狀態已更新'
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': '尚有產品未完成出貨'
                }), 400

    except Exception as e:
        print(f"Error in update_order_shipped: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/update-quantity', methods=['POST'])
def update_order_quantity():
    try:
        data = request.get_json()
        
        if not data or 'order_detail_id' not in data or 'quantity' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少必要參數'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 先獲取原始訂單資訊
            cursor.execute("""
                SELECT od.*, p.name as product_name, o.order_number
                FROM order_details od
                JOIN orders o ON od.order_id = o.id
                JOIN products p ON od.product_id = p.id
                WHERE od.id = %s
            """, (data['order_detail_id'],))
            
            old_order = cursor.fetchone()
            if not old_order:
                return jsonify({
                    'status': 'error',
                    'message': '找不到訂單明細'
                }), 404

            # 更新數量
            cursor.execute("""
                UPDATE order_details 
                SET product_quantity = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
            """, (data['quantity'], data['order_detail_id']))
            
            if not cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': '更新失敗'
                }), 400

            # 記錄日誌
            old_shipping_date = old_order[6].strftime('%Y-%m-%d') if old_order[6] else '待確認'
            old_data = {
                'message': {
                    'order_number': old_order[-1],
                    'status': old_order[5],
                    'products': [{
                        'name': old_order[-2],
                        'quantity': str(old_order[3]),
                        'shipping_date': old_shipping_date,
                        'supplier_note': old_order[8] if old_order[8] else '-'
                    }]
                }
            }
            
            new_data = {
                'message': {
                    'order_number': old_order[-1],
                    'status': old_order[5],
                    'products': [{
                        'name': old_order[-2],
                        'quantity': str(data['quantity']),
                        'shipping_date': old_shipping_date,
                        'supplier_note': old_order[8] if old_order[8] else '-'
                    }]
                }
            }

            log_operation(
                table_name='orders',
                operation_type='修改',
                record_id=old_order[1],  # order_id
                old_data=old_data,
                new_data=new_data,
                performed_by=session.get('admin_id'),
                user_type='管理員'
            )

            conn.commit()
            
            return jsonify({
                'status': 'success',
                'message': '數量更新成功'
            })

    except Exception as e:
        print(f"Error in update_order_quantity: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route("/<int:order_id>", methods=['PUT'])
@admin_required
def update_order(order_id):
    try:
        data = request.get_json()
        admin_id = session.get('admin_id')
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 获取旧数据
            cursor.execute("""
                SELECT o.*, 
                       json_agg(json_build_object(
                           'id', od.id,
                           'product_id', od.product_id,
                           'product_quantity', od.product_quantity,
                           'product_unit', od.product_unit,
                           'order_status', od.order_status,
                           'remark', od.remark,
                           'supplier_note', od.supplier_note
                       )) as order_details
                FROM orders o
                LEFT JOIN order_details od ON o.id = od.order_id
                WHERE o.id = %s
                GROUP BY o.id
            """, (order_id,))
            
            old_data = cursor.fetchone()
            if not old_data:
                return jsonify({"status": "error", "message": "訂單不存在"}), 404
            
            # 转换为字典
            old_data_dict = {
                'id': old_data[0],
                'order_number': old_data[1],
                'customer_id': old_data[2],
                'order_confirmed': old_data[3],
                'order_shipped': old_data[4],
                'created_at': old_data[5].isoformat() if old_data[5] else None,
                'updated_at': old_data[6].isoformat() if old_data[6] else None,
                'order_details': old_data[7]
            }
            
            # 执行更新
            update_fields = []
            update_values = []
            
            if 'order_confirmed' in data:
                update_fields.append("order_confirmed = %s")
                update_values.append(data['order_confirmed'])
                
            if 'order_shipped' in data:
                update_fields.append("order_shipped = %s")
                update_values.append(data['order_shipped'])
            
            if update_fields:
                update_fields.append("updated_at = NOW()")
                query = f"""
                    UPDATE orders 
                    SET {", ".join(update_fields)}
                    WHERE id = %s
                    RETURNING *
                """
                cursor.execute(query, update_values + [order_id])
                new_data = cursor.fetchone()
                
                # 获取更新后的完整数据
                cursor.execute("""
                    SELECT o.*, 
                           json_agg(json_build_object(
                               'id', od.id,
                               'product_id', od.product_id,
                               'product_quantity', od.product_quantity,
                               'product_unit', od.product_unit,
                               'order_status', od.order_status,
                               'remark', od.remark,
                               'supplier_note', od.supplier_note
                           )) as order_details
                    FROM orders o
                    LEFT JOIN order_details od ON o.id = od.order_id
                    WHERE o.id = %s
                    GROUP BY o.id
                """, (order_id,))
                
                new_data = cursor.fetchone()
                new_data_dict = {
                    'id': new_data[0],
                    'order_number': new_data[1],
                    'customer_id': new_data[2],
                    'order_confirmed': new_data[3],
                    'order_shipped': new_data[4],
                    'created_at': new_data[5].isoformat() if new_data[5] else None,
                    'updated_at': new_data[6].isoformat() if new_data[6] else None,
                    'order_details': new_data[7]
                }
                
                # 记录日志
                log_operation(
                    table_name='orders',
                    operation_type='修改',
                    record_id=order_id,
                    old_data=old_data_dict,
                    new_data=new_data_dict,
                    performed_by=admin_id,
                    user_type='管理員'
                )
                
                conn.commit()
                return jsonify({"status": "success", "data": new_data_dict})
            
            return jsonify({"status": "error", "message": "沒有要更新的數據"}), 400
            
    except Exception as e:
        print(f"Error updating order: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@order_bp.route("/<int:order_id>", methods=['DELETE'])
@admin_required
def delete_order(order_id):
    try:
        admin_id = session.get('admin_id')
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 获取要删除的订单数据
            cursor.execute("""
                SELECT o.*, 
                       json_agg(json_build_object(
                           'id', od.id,
                           'product_id', od.product_id,
                           'product_quantity', od.product_quantity,
                           'product_unit', od.product_unit,
                           'order_status', od.order_status,
                           'remark', od.remark,
                           'supplier_note', od.supplier_note
                       )) as order_details
                FROM orders o
                LEFT JOIN order_details od ON o.id = od.order_id
                WHERE o.id = %s
                GROUP BY o.id
            """, (order_id,))
            
            old_data = cursor.fetchone()
            if not old_data:
                return jsonify({"status": "error", "message": "訂單不存在"}), 404
                
            # 转换为字典
            old_data_dict = {
                'id': old_data[0],
                'order_number': old_data[1],
                'customer_id': old_data[2],
                'order_confirmed': old_data[3],
                'order_shipped': old_data[4],
                'created_at': old_data[5].isoformat() if old_data[5] else None,
                'updated_at': old_data[6].isoformat() if old_data[6] else None,
                'order_details': old_data[7]
            }
            
            # 删除订单详情
            cursor.execute("DELETE FROM order_details WHERE order_id = %s", (order_id,))
            
            # 删除订单
            cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
            
            # 记录日志
            log_operation(
                table_name='orders',
                operation_type='刪除',
                record_id=order_id,
                old_data=old_data_dict,
                new_data=None,
                performed_by=admin_id,
                user_type='管理員'
            )
            
            conn.commit()
            return jsonify({"status": "success", "message": "訂單已刪除"})
            
    except Exception as e:
        print(f"Error deleting order: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500 