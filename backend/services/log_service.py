import json
from datetime import datetime
from typing import Dict, Any, Optional

class LogService:
    def __init__(self, db_connection):
        self.conn = db_connection
        
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """計算數據變更"""
        print(f"Processing changes - operation_type: {operation_type}")
        print(f"Old data: {json.dumps(old_data, ensure_ascii=False, indent=2) if old_data else None}")
        print(f"New data: {json.dumps(new_data, ensure_ascii=False, indent=2) if new_data else None}")

        # 處理新增和刪除操作
        if operation_type in ['新增', '刪除']:
            data = new_data if operation_type == '新增' else old_data
            if isinstance(data, dict) and 'message' in data:
                try:
                    # 嘗試解析 JSON 格式的消息
                    message_data = json.loads(data['message']) if isinstance(data['message'], str) else data['message']
                    if isinstance(message_data, dict):
                        # 處理結構化數據
                        products_info = []
                        for product in message_data.get('products', []):
                            product_info = {
                                'name': product.get('name', ''),
                                'quantity': str(product.get('quantity', '')),
                                'shipping_date': product.get('shipping_date', '待確認'),
                                'supplier_note': product.get('supplier_note', '-'),
                                'remark': product.get('remark', '-')
                            }
                            if not product_info['name'] and 'product' in product:
                                product_info['name'] = product['product']
                            products_info.append(product_info)

                        return {
                            'message': {
                                'order_number': message_data.get('order_number', ''),
                                'status': message_data.get('status', '待確認'),
                                'products': products_info
                            },
                            'operation_type': operation_type
                        }
                except json.JSONDecodeError:
                    # 如果不是 JSON 格式，按原來的方式處理
                    message_parts = data['message'].split('、')
                    order_info = {}
                    products_info = []
                    current_product = {}
                    
                    for part in message_parts:
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.strip()
                            value = value.strip()
                            if key == '訂單號':
                                order_info['order_number'] = value
                            elif key == '狀態':
                                order_info['status'] = value if value != 'undefined' else '待確認'
                            elif key == '產品':
                                if current_product:
                                    products_info.append(current_product)
                                current_product = {'name': value}
                            elif key == '數量':
                                if current_product:
                                    current_product['quantity'] = value
                            elif key == '出貨日期':
                                if current_product:
                                    current_product['shipping_date'] = value if value not in ['undefined', ''] else '待確認'
                            elif key == '備註':
                                if current_product:
                                    current_product['remark'] = value if value not in ['-', '', 'undefined'] else '-'
                            elif key == '供應商備註':
                                if current_product:
                                    current_product['supplier_note'] = value if value not in ['-', '', 'undefined'] else '-'

                    if current_product:
                        products_info.append(current_product)

                return {
                        'message': {
                            'order_number': order_info.get('order_number', ''),
                            'status': order_info.get('status', '待確認'),
                            'products': products_info
                        },
                        'operation_type': operation_type
                    }
        
        # 處理修改和審核操作
        if isinstance(old_data, dict) and isinstance(new_data, dict):
            # 處理審核操作
            if operation_type == '審核':
                # 获取订单号
                order_number = ''
                status_after = '已確認'  # 默认状态为已确认
                
                if isinstance(new_data, dict):
                    if isinstance(new_data.get('message'), str):
                        # 处理字符串格式
                        parts = new_data['message'].split('、')
                        for part in parts:
                            if '訂單號:' in part:
                                order_number = part.split(':')[1]
                                break
                    elif isinstance(new_data.get('message'), dict):
                        order_number = new_data['message'].get('order_number', '')
                        # 获取实际状态，可能是已确认或已取消
                        status_after = new_data['message'].get('status', '已確認')
                
                # 构建简化的审核变更记录
                audit_changes = {
                    'message': {
                        'order_number': order_number,
                        'status': {
                            'before': '待確認',
                            'after': status_after
                        }
                    }
                }
                
                return audit_changes

            # 處理一般修改操作
            old_message = old_data.get('message', '')
            new_message = new_data.get('message', '')
            
            # 解析字符串格式的消息
            if isinstance(old_message, str):
                old_parts = {}
                for part in old_message.split('、'):
                    if ':' in part:
                        key, value = part.split(':', 1)
                        old_parts[key.strip()] = value.strip()
                old_message = {
                    'order_number': old_parts.get('訂單號', ''),
                    'status': old_parts.get('狀態', '待確認'),
                    'products': [{
                        'name': old_parts.get('產品', ''),
                        'quantity': old_parts.get('數量', ''),
                        'shipping_date': old_parts.get('出貨日期', '待確認'),
                        'remark': old_parts.get('備註', '-'),
                        'supplier_note': old_parts.get('供應商備註', '-')
                    }]
                }
            
            if isinstance(new_message, str):
                new_parts = {}
                for part in new_message.split('、'):
                    if ':' in part:
                        key, value = part.split(':', 1)
                        new_parts[key.strip()] = value.strip()
                new_message = {
                    'order_number': new_parts.get('訂單號', ''),
                    'status': new_parts.get('狀態', '待確認'),
                    'products': [{
                        'name': new_parts.get('產品', ''),
                        'quantity': new_parts.get('數量', ''),
                        'shipping_date': new_parts.get('出貨日期', '待確認'),
                        'remark': new_parts.get('備註', '-'),
                        'supplier_note': new_parts.get('供應商備註', '-')
                    }]
                }

            try:
                products_changes = []
                
                # 處理所有產品的變更
                for i, new_product in enumerate(new_message.get('products', [])):
                    changes = {}
                    # 獲取對應的舊產品信息，如果索引超出範圍則使用空字典
                    old_product = old_message.get('products', [])[i] if i < len(old_message.get('products', [])) else {}
                    
                    # 檢查數量變更
                    if old_product.get('quantity', '') != new_product.get('quantity', ''):
                        changes['quantity'] = {
                            'before': old_product.get('quantity', ''),
                            'after': new_product.get('quantity', '')
                        }
                    
                    # 檢查出貨日期變更
                    if old_product.get('shipping_date', '') != new_product.get('shipping_date', ''):
                        changes['shipping_date'] = {
                            'before': old_product.get('shipping_date', '待確認'),
                            'after': new_product.get('shipping_date', '待確認')
                        }
                    
                    # 檢查客戶備註變更
                    if old_product.get('remark', '') != new_product.get('remark', ''):
                        changes['remark'] = {
                            'before': old_product.get('remark', '-'),
                            'after': new_product.get('remark', '-')
                        }
                    
                    # 檢查供應商備註變更
                    if old_product.get('supplier_note', '') != new_product.get('supplier_note', ''):
                        changes['supplier_note'] = {
                            'before': old_product.get('supplier_note', '-'),
                            'after': new_product.get('supplier_note', '-')
                        }
                    
                    if changes:  # 如果有變更，添加到產品變更列表
                        products_changes.append({
                            'name': new_product.get('name', ''),
                            'changes': changes
                        })
                
                if products_changes:  # 如果有產品變更，返回修改操作
                    return {
                        'message': {
                            'order_number': new_message.get('order_number', '') if isinstance(new_message, dict) else '',
                            'status': new_message.get('status', '待確認') if isinstance(new_message, dict) else '待確認',
                            'products': products_changes
                        },
                        'operation_type': '修改'
                    }
                
            except Exception as e:
                print(f"Error processing changes: {str(e)}")
                return {'message': '處理變更時發生錯誤', 'operation_type': None}
        
        return {'message': '無變更', 'operation_type': None}

    def log_operation(self, table_name: str, operation_type: str, record_id: int, 
                     old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], 
                     performed_by: int, user_type: str) -> bool:
        """記錄操作日誌"""
        try:
            print(f"Received log operation request:")
            print(f"Table: {table_name}")
            print(f"Operation: {operation_type}")
            print(f"Record ID: {record_id}")
            
            # 處理日期序列化
            def serialize_datetime(obj):
                if isinstance(obj, datetime):
                    return obj.strftime('%Y-%m-%d %H:%M:%S')
                return obj

            # 序列化數據
            if old_data:
                old_data = json.loads(json.dumps(old_data, default=serialize_datetime, ensure_ascii=False))
            if new_data:
                new_data = json.loads(json.dumps(new_data, default=serialize_datetime, ensure_ascii=False))

            print(f"New data: {json.dumps(new_data, ensure_ascii=False)}")
            print(f"Performed by: {performed_by}")
            print(f"User type: {user_type}")
            
            # 檢查是否存在最近的日誌記錄
            cursor = self.conn.cursor()
            
            if operation_type == '修改':
                # 檢查是否有最近的修改記錄可以合併
                cursor.execute("""
                    SELECT id, operation_detail 
                    FROM logs 
                    WHERE table_name = %s 
                    AND operation_type = %s 
                    AND record_id = %s 
                    AND performed_by = %s 
                    AND created_at > NOW() - INTERVAL '5 seconds'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (table_name, operation_type, record_id, performed_by))
                
                recent_log = cursor.fetchone()
                
                # 如果找到最近的記錄，嘗試合併
                if recent_log:
                    log_id, recent_detail = recent_log
                    
                    try:
                        # 解析現有日誌詳情
                        if isinstance(recent_detail, str):
                            recent_detail = json.loads(recent_detail)
                        
                        # 確保新數據有正確的格式
                        if isinstance(new_data, dict) and 'message' in new_data:
                            # 獲取訂單號和狀態
                            order_number = new_data['message'].get('order_number', '')
                            status = new_data['message'].get('status', '待確認')
                            
                            # 如果沒有現有的操作詳情，創建一個基本結構
                            if not recent_detail or 'message' not in recent_detail:
                                recent_detail = {
                                    'message': {
                                        'order_number': order_number,
                                        'status': status,
                                        'products': []
                                    },
                                    'operation_type': '修改'
                                }
                            
                            # 獲取當前產品信息
                            current_products = []
                            if 'products' in new_data['message']:
                                current_products = new_data['message']['products']

                            # 處理所有產品的變更
                            for current_product in current_products:
                                if current_product and 'name' in current_product and 'changes' in current_product:
                                    # 檢查是否已有此產品的變更記錄
                                    product_found = False
                                    
                                    for product in recent_detail['message'].get('products', []):
                                        if product.get('name') == current_product['name']:
                                            # 合併變更
                                            for change_type, change_value in current_product['changes'].items():
                                                product['changes'][change_type] = change_value
                                            product_found = True
                                            break
                                    
                                    # 如果沒有找到此產品，添加新的產品變更
                                    if not product_found:
                                        if 'products' not in recent_detail['message']:
                                            recent_detail['message']['products'] = []
                                        recent_detail['message']['products'].append(current_product)

                            # 更新日誌記錄
                            cursor.execute("""
                                UPDATE logs 
                                SET operation_detail = %s::jsonb,
                                    created_at = NOW()
                                WHERE id = %s
                            """, (json.dumps(recent_detail, ensure_ascii=False), log_id))
                            
                            self.conn.commit()
                            print(f"Successfully merged log for {operation_type} operation")
                            return True
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        print(f"Error merging log details: {str(e)}")
                
                # 如果沒有找到最近的記錄或合併失敗，創建新記錄
                if isinstance(new_data, dict) and 'message' in new_data and 'products' in new_data['message']:
                    # 計算當前變更詳情
                    operation_detail = {
                        'message': {
                            'order_number': new_data['message'].get('order_number', ''),
                            'status': new_data['message'].get('status', '待確認'),
                            'products': new_data['message']['products']  # 記錄所有產品，而不是只取第一個
                        },
                        'operation_type': '修改'
                    }
                    
                    cursor.execute("""
                        INSERT INTO logs 
                        (table_name, operation_type, record_id, operation_detail, 
                         performed_by, user_type, created_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, NOW())
                    """, (
                        table_name,
                        operation_type,
                        record_id,
                        json.dumps(operation_detail, ensure_ascii=False),
                        performed_by,
                        user_type
                    ))
                    self.conn.commit()
                    print(f"日志记录成功: {operation_type} - {table_name} - ID: {record_id}")
                    return True
                else:
                    # 如果數據格式不正確，使用原始的變更計算方法
                    operation_detail = self._get_changes(old_data, new_data, operation_type)
                    
                    if operation_detail and operation_detail.get('operation_type') is not None:
                        cursor.execute("""
                            INSERT INTO logs 
                            (table_name, operation_type, record_id, operation_detail, 
                             performed_by, user_type, created_at)
                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, NOW())
                        """, (
                            table_name,
                            operation_type,
                            record_id,
                            json.dumps(operation_detail, ensure_ascii=False),
                            performed_by,
                            user_type
                        ))
                        self.conn.commit()
                        print(f"日志记录成功: {operation_type} - {table_name} - ID: {record_id}")
                        return True
            else:
                # 對於非修改操作，使用原始的變更計算方法
                operation_detail = self._get_changes(old_data, new_data, operation_type)
                
                if operation_type in ['新增', '刪除', '審核'] or \
                   (operation_detail and operation_detail.get('operation_type') is not None):
                    cursor.execute("""
                        INSERT INTO logs 
                        (table_name, operation_type, record_id, operation_detail, 
                         performed_by, user_type, created_at)
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, NOW())
                    """, (
                        table_name,
                        operation_type,
                        record_id,
                        json.dumps(operation_detail, ensure_ascii=False),
                        performed_by,
                        user_type
                    ))
                    self.conn.commit()
                    print(f"日志记录成功: {operation_type} - {table_name} - ID: {record_id}")
                    return True
            
            print(f"Failed to log {operation_type} operation")
            return False
            
        except Exception as e:
            print(f"Error logging operation: {str(e)}")
            self.conn.rollback()
            return False

    def get_logs(self,
                table_name: Optional[str] = None,
                operation_type: Optional[str] = None,
                start_date: Optional[str] = None,
                end_date: Optional[str] = None,
                user_type: Optional[str] = None,
                performed_by: Optional[int] = None,
                limit: int = 100,
                offset: int = 0) -> tuple:
        """
        獲取日志記錄
        
        參數:
            table_name: 表名篩選
            operation_type: 操作類型篩選
            start_date: 開始日期
            end_date: 結束日期
            user_type: 用戶類型篩選
            performed_by: 操作者ID篩選
            limit: 返回記錄數限制
            offset: 分頁偏移量
            
        返回:
            tuple: (日志記錄列表, 總記錄數)
        """
        try:
            cursor = self.conn.cursor()
            
            # 构建基础查询
            base_query = """
                SELECT 
                    l.created_at,
                    l.user_type,
                    COALESCE(a.admin_name, c.company_name) as performer_name,
                    l.table_name,
                    CASE 
                        WHEN l.table_name = 'orders' THEN o.order_number
                        WHEN l.table_name = 'products' THEN p.name
                        WHEN l.table_name = 'customers' THEN cust.company_name
                        WHEN l.table_name = 'administrators' THEN adm.admin_name
                        ELSE l.record_id::text
                    END as record_detail,
                    l.operation_type,
                    l.operation_detail,
                    l.id,
                    l.performed_by
                FROM logs l
                LEFT JOIN administrators a ON l.performed_by = a.id AND l.user_type = '管理員'
                LEFT JOIN customers c ON l.performed_by = c.id AND l.user_type = '客戶'
                LEFT JOIN orders o ON l.table_name = 'orders' AND l.record_id = o.id
                LEFT JOIN products p ON l.table_name = 'products' AND l.record_id = p.id
                LEFT JOIN customers cust ON l.table_name = 'customers' AND l.record_id = cust.id
                LEFT JOIN administrators adm ON l.table_name = 'administrators' AND l.record_id = adm.id
            """
            
            conditions = []
            params = []
            
            if table_name:
                conditions.append("l.table_name = %s")
                params.append(table_name)
            
            if operation_type:
                conditions.append("l.operation_type = %s")
                params.append(operation_type)
                
            if start_date:
                conditions.append("l.created_at >= %s")
                params.append(start_date)
                
            if end_date:
                conditions.append("l.created_at <= %s")
                params.append(end_date)
                
            if user_type:
                conditions.append("l.user_type = %s")
                params.append(user_type)
                
            if performed_by:
                conditions.append("l.performed_by = %s")
                params.append(performed_by)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 获取总记录数
            count_query = f"""
                SELECT COUNT(*) 
                FROM logs l 
                WHERE {where_clause}
            """
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]
            
            # 获取日志记录
            query = f"""
                {base_query}
                WHERE {where_clause}
                ORDER BY l.created_at DESC
                LIMIT %s OFFSET %s
            """
            
            cursor.execute(query, params + [limit, offset])
            logs = cursor.fetchall()
            
            # 转换日志记录为字典列表
            log_list = []
            for log in logs:
                try:
                    operation_detail = log[6]
                    if isinstance(operation_detail, str):
                        try:
                            operation_detail = json.loads(operation_detail)
                        except json.JSONDecodeError:
                            operation_detail = {'message': operation_detail}
                except Exception as e:
                    print(f"Error processing operation_detail: {e}")
                    operation_detail = {'message': str(log[6])}

                log_dict = {
                    'created_at': log[0].strftime('%Y-%m-%d %H:%M:%S'),
                    'user_type': log[1],
                    'performer_name': log[2],
                    'table_name': log[3],
                    'record_detail': log[4],
                    'operation_type': log[5],
                    'operation_detail': operation_detail,
                    'id': log[7],
                    'performed_by': log[8]
                }
                log_list.append(log_dict)
            
            return logs, total_count
            
        except Exception as e:
            print(f"Error getting logs: {str(e)}")
            return [], 0 