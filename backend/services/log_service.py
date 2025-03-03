import json
from datetime import datetime
from typing import Dict, Any, Optional
from .log_service_registry import LogServiceRegistry

class LogService:
    """日誌服務類，處理日誌記錄和查詢"""
    
    def __init__(self, db_connection):
        """初始化日誌服務"""
        self.db_connection = db_connection
    
    def log_operation(self, table_name, operation_type, record_id, old_data=None, new_data=None, performed_by=None, user_type=None):
        """記錄操作日誌"""
        try:
            # 使用日誌服務註冊表獲取適當的日誌服務
            log_service = LogServiceRegistry.get_service(self.db_connection, table_name)
            
            # 使用獲取的日誌服務記錄操作
            return log_service.log_operation(
                table_name=table_name,
                operation_type=operation_type,
                record_id=record_id,
                old_data=old_data,
                new_data=new_data,
                performed_by=performed_by,
                user_type=user_type
            )
        except Exception as e:
            print(f"Error logging operation: {str(e)}")
            raise
    
    def get_logs(self, table_name=None, operation_type=None, start_date=None, end_date=None, user_type=None, performed_by=None, limit=50, offset=0):
        """獲取日誌記錄"""
        try:
            # 使用基礎日誌服務獲取日誌記錄
            log_service = LogServiceRegistry.get_service(self.db_connection)
            
            # 使用獲取的日誌服務查詢日誌
            return log_service.get_logs(
                table_name=table_name,
                operation_type=operation_type,
                start_date=start_date,
                end_date=end_date,
                user_type=user_type,
                performed_by=performed_by,
                limit=limit,
                offset=offset
            )
        except Exception as e:
            print(f"Error getting logs: {str(e)}")
            raise

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
                status_before = '待確認'  # 默认之前的状态为待确认
                
                if isinstance(new_data, dict):
                    if isinstance(new_data.get('message'), str):
                        # 处理字符串格式
                        parts = new_data['message'].split('、')
                        for part in parts:
                            if '訂單號:' in part:
                                order_number = part.split(':')[1]
                                break
                            elif '狀態:' in part:
                                status_after = part.split(':')[1]
                    elif isinstance(new_data.get('message'), dict):
                        order_number = new_data['message'].get('order_number', '')
                        
                        # 检查是否有明确的状态变更信息
                        if 'status' in new_data['message'] and isinstance(new_data['message']['status'], dict):
                            status_before = new_data['message']['status'].get('before', '待確認')
                            status_after = new_data['message']['status'].get('after', '已確認')
                        else:
                            # 判断整张订单的状态
                            all_cancelled = True
                            has_confirmed = False
                            
                            # 检查所有产品的状态
                            if 'products' in new_data['message']:
                                for product in new_data['message'].get('products', []):
                                    product_status = product.get('status', '')
                                    if product_status == '已確認':
                                        has_confirmed = True
                                        all_cancelled = False
                                        break
                                    elif product_status != '已取消':
                                        all_cancelled = False
                            
                            # 根据产品状态确定整张订单的状态
                            if has_confirmed:
                                status_after = '已確認'
                            elif all_cancelled:
                                status_after = '已取消'
                            else:
                                # 如果没有明确的产品状态信息，使用订单级别的状态
                                status_after = new_data['message'].get('status', '已確認')
                
                # 构建简化的审核变更记录
                audit_changes = {
                    'message': {
                        'order_number': order_number,
                        'status': {
                            'before': status_before,
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
                            'products': products_changes
                        },
                        'operation_type': '修改'
                    }
                
            except Exception as e:
                print(f"Error processing changes: {str(e)}")
                return {'message': '處理變更時發生錯誤', 'operation_type': None}
        
        return {'message': '無變更', 'operation_type': None} 