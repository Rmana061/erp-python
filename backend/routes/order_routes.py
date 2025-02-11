from flask import Blueprint, request, jsonify
from backend.config.database import get_db_connection
from datetime import datetime

order_bp = Blueprint('order', __name__, url_prefix='/api')

@order_bp.route('/orders/create', methods=['POST'])
def create_order():
    try:
        data = request.json
        print("Received order data:", data)
        
        # 驗證必填字段
        required_fields = ['order_number', 'customer_id']
        for field in required_fields:
            if field not in data:

                return jsonify({
                    'status': 'error',
                    'message': f'缺少必填欄位: {field}'
                }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            try:
                # 1. 首先創建主訂單
                order_sql = """
                    INSERT INTO orders (order_number, customer_id, created_at)
                    VALUES (%s, %s, %s)
                    RETURNING id;

                """
                
                cursor.execute(order_sql, (
                    data['order_number'],
                    data['customer_id'],
                    datetime.now()
                ))
                
                order_id = cursor.fetchone()[0]

                # 2. 然後創建訂單詳情
                details_sql = """
                    INSERT INTO order_details (
                        order_id, product_id, product_quantity,
                        product_unit, order_status, shipping_date,
                        remark, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """

                # 遍歷所有產品並創建詳情記錄
                for product in data['products']:
                    cursor.execute(details_sql, (
                        order_id,
                        product['product_id'],
                        product['product_quantity'],
                        product['product_unit'],
                        product['order_status'],
                        product['shipping_date'] if product['shipping_date'] else None,
                        product.get('remark', ''),
                        datetime.now()
                    ))
                
                conn.commit()
                
                return jsonify({
                    'status': 'success',
                    'message': '訂單創建成功',
                    'data': {
                        'order_id': order_id,
                        'order_number': data['order_number']
                    }
                }), 201
                
            except Exception as e:
                conn.rollback()
                raise e
            
            finally:
                cursor.close()
                
    except Exception as e:
        print(f"Error in create_order: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/list', methods=['POST'])
def get_orders():
    try:
        data = request.json
        customer_id = data.get('customer_id')
        if not customer_id:
            return jsonify({
                'status': 'error',
                'message': '缺少客戶ID'
            }), 400

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
            
            cursor.execute(sql, (customer_id,))
            
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
                        'created_at': row['order_created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['order_created_at'] else None,
                        'products': []
                    }
                
                orders[order_id]['products'].append({
                    'id': row['detail_id'],
                    'product_id': row['product_id'],
                    'product_name': row['product_name'],
                    'product_quantity': row['product_quantity'],
                    'product_unit': row['product_unit'],
                    'order_status': row['order_status'],
                    'shipping_date': row['shipping_date'].strftime('%Y-%m-%d') if row['shipping_date'] else None,
                    'remark': row['remark'],
                    'supplier_note': row['supplier_note']
                })
            
            cursor.close()
            
            # 將字典轉換為列表並返回
            orders_list = list(orders.values())
            
            return jsonify({
                'status': 'success',
                'data': orders_list
            })
            
    except Exception as e:
        print(f"Error in get_orders: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/cancel', methods=['POST'])
def cancel_order():
    try:
        data = request.json
        if not data or 'order_number' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少訂單編號'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 檢查訂單狀態是否為待確認
            cursor.execute("""
                SELECT od.order_status 
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                WHERE o.order_number = %s
            """, (data['order_number'],))

            statuses = cursor.fetchall()
            if not statuses:
                return jsonify({
                    'status': 'error',
                    'message': '找不到該訂單'
                }), 404

            # 檢查所有產品是否都是待確認狀態
            for status in statuses:
                if status[0] != '待確認':
                    return jsonify({
                        'status': 'error',
                        'message': '只有待確認狀態的訂單可以取消'
                    }), 400

            # 刪除訂單詳情
            cursor.execute("""
                DELETE FROM order_details
                USING orders
                WHERE orders.id = order_details.order_id
                AND orders.order_number = %s
            """, (data['order_number'],))

            # 刪除主訂單
            cursor.execute("""
                DELETE FROM orders
                WHERE order_number = %s
            """, (data['order_number'],))

            conn.commit()
            cursor.close()

            return jsonify({
                'status': 'success',
                'message': '訂單已取消'
            })

    except Exception as e:
        print(f"Error in cancel_order: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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
                    od.remark
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
                    'date': row['order_date'].isoformat(),  # 使用 ISO 格式返回時間
                    'customer': row['customer_name'],
                    'item': row['product_name'],
                    'quantity': str(row['product_quantity']),
                    'unit': row['product_unit'],
                    'orderNumber': row['order_number'],
                    'shipping_date': row['shipping_date'].isoformat() if row['shipping_date'] else None,
                    'note': row['remark'] or '',
                    'status': row['order_status']
                })
            
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'data': orders
            })
            
    except Exception as e:
        print(f"Error in get_today_orders: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@order_bp.route('/orders/update-status', methods=['POST'])
def update_order_status():
    try:
        data = request.json
        if not data or 'order_id' not in data or 'status' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少必要參數'
            }), 400

        # 如果是核准訂單，需要檢查出貨日期
        if data['status'] == '已確認' and 'shipping_date' not in data:
            return jsonify({
                'status': 'error',
                'message': '核准訂單時需要提供出貨日期'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 更新訂單狀態和出貨日期
            update_sql = """
                UPDATE order_details 
                SET order_status = %s,
                    shipping_date = %s,
                    supplier_note = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING order_id;
            """
            
            shipping_date = data.get('shipping_date') if data['status'] == '已確認' else None
            supplier_note = data.get('supplier_note')
            cursor.execute(update_sql, (data['status'], shipping_date, supplier_note, data['order_id']))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    'status': 'error',
                    'message': '找不到該訂單'
                }), 404

            # 更新主訂單的更新時間
            cursor.execute("""
                UPDATE orders 
                SET updated_at = NOW()
                WHERE id = %s;
            """, (result[0],))

            conn.commit()
            cursor.close()

            return jsonify({
                'status': 'success',
                'message': '訂單狀態更新成功'
            })

    except Exception as e:
        print(f"Error in update_order_status: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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
            
            # 檢查是否所有產品都是已確認或已取消狀態
            all_confirmed_or_cancelled = all(status in ['已確認', '已取消'] for status in statuses)
            
            if all_confirmed_or_cancelled:
                # 更新訂單確認狀態
                cursor.execute("""
                    UPDATE orders 
                    SET order_confirmed = true,
                        updated_at = NOW()
                    WHERE order_number = %s
                """, (data['order_number'],))

                conn.commit()
                
                return jsonify({
                    'status': 'success',
                    'message': '訂單確認狀態已更新'
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': '尚有產品未完成審核'
                }), 400

    except Exception as e:
        print(f"Error in update_order_confirmed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

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
            
            has_confirmed = any(
                status == '已確認'
                for status in statuses
            )
            
            if not has_confirmed and all_processed:
                # 更新訂單出貨狀態
                cursor.execute("""
                    UPDATE orders 
                    SET order_shipped = true,
                        updated_at = NOW()
                    WHERE order_number = %s
                """, (data['order_number'],))

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