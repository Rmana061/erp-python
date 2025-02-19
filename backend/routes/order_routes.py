from flask import Blueprint, request, jsonify, session
from backend.config.database import get_db_connection
from datetime import datetime
from backend.utils.email_utils import EmailSender
import threading

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

@order_bp.route('/orders/create', methods=['POST'])
def create_order():
    try:
        data = request.json
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
                        remark, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                """, (
                    order_id,
                    product['product_id'],
                    product['product_quantity'],
                    product['product_unit'],
                    product['order_status'],
                    product['shipping_date'],
                    product.get('remark', '')
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
            cursor.execute(ORDER_DETAIL_SQL, (data['order_number'],))
            order_info = cursor.fetchone()
            
            if not order_info:
                return error_response('找不到該訂單', 404)

            # 檢查所有產品是否都是待確認狀態
            all_pending = all(item['order_status'] == '待確認' for item in order_info[4])
            if not all_pending:
                return error_response('只有待確認狀態的訂單可以取消', 400)

            # 準備郵件數據
            email_data = {
                'order_number': order_info[0],
                'cancel_date': format_datetime(datetime.now()),
                'items': order_info[4]
            }

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
                RETURNING 1;
            """, (data['order_number'], data['order_number']))

            if not cursor.fetchone():
                return error_response('訂單刪除失敗', 400)

            conn.commit()

            # 異步發送取消訂單郵件
            threading.Thread(
                target=send_cancel_email,
                args=(order_info[3], email_data)
            ).start()

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
    try:
        data = request.json
        if not data or 'order_id' not in data or 'status' not in data:
            return error_response('缺少必要參數')

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取出貨日期和供應商備註
            shipping_date = None
            supplier_note = None
            if data['status'] == '已出貨':
                cursor.execute("""
                    SELECT shipping_date, supplier_note
                    FROM order_details
                    WHERE id = %s
                """, (data['order_id'],))
                result = cursor.fetchone()
                if result:
                    shipping_date, supplier_note = result
            else:
                shipping_date = data.get('shipping_date')
                supplier_note = data.get('supplier_note')

            # 更新訂單狀態
            cursor.execute("""
                UPDATE order_details 
                SET order_status = %s,
                    shipping_date = COALESCE(%s, shipping_date),
                    supplier_note = COALESCE(%s, supplier_note),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING order_id, (
                    SELECT order_number 
                    FROM orders 
                    WHERE id = order_details.order_id
                );
            """, (data['status'], shipping_date, supplier_note, data['order_id']))
            
            result = cursor.fetchone()
            if not result:
                return error_response('找不到該訂單', 404)

            order_id, order_number = result

            # 如果狀態是已駁回，發送郵件通知
            if data['status'] == '已取消':
                cursor.execute(ORDER_DETAIL_SQL, (str(order_number),))
                order_info = cursor.fetchone()
                if order_info:
                    email_data = {
                        'order_number': order_info[0],
                        'confirm_date': format_datetime(order_info[2]),
                        'items': order_info[4]
                    }
                    threading.Thread(
                        target=lambda: EmailSender().send_order_rejected(order_info[3], email_data)
                    ).start()

            # 更新主訂單時間戳
            cursor.execute("""
                UPDATE orders 
                SET updated_at = NOW()
                WHERE id = %s;
            """, (order_id,))

            conn.commit()
            return success_response(message='訂單狀態更新成功')

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
            
            # 先檢查訂單狀態是否為待確認
            cursor.execute("""
                SELECT od.id, o.order_confirmed, o.order_shipped
                FROM order_details od
                JOIN orders o ON od.order_id = o.id
                WHERE od.id = %s
            """, (data['order_detail_id'],))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    'status': 'error',
                    'message': '找不到訂單明細'
                }), 404
                
            if result[1] or result[2]:
                return jsonify({
                    'status': 'error',
                    'message': '只能修改待確認狀態的訂單'
                }), 400

            # 更新數量
            cursor.execute("""
                UPDATE order_details 
                SET product_quantity = %s,
                    updated_at = NOW()
                WHERE id = %s AND order_status = '待確認'
                RETURNING id
            """, (data['quantity'], data['order_detail_id']))
            
            if not cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': '更新失敗，可能訂單狀態已改變'
                }), 400

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