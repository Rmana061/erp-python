import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService

class OrderLogService(BaseLogService):
    """訂單日誌服務類，處理訂單相關的日誌邏輯"""
    
    def __init__(self, db_connection=None):
        """初始化訂單日誌服務
        
        Args:
            db_connection: 數據庫連接對象
        """
        super().__init__(db_connection)
        self._order_changes = {}  # 使用字典按訂單號存儲變更
        self._last_log_time = {}  # 記錄每個訂單的最後日誌時間
        
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理訂單變更的方法"""
        print(f"Processing order changes - operation_type: {operation_type}")
        print(f"Old data: {json.dumps(old_data, ensure_ascii=False, indent=2) if old_data else None}")
        print(f"New data: {json.dumps(new_data, ensure_ascii=False, indent=2) if new_data else None}")

        try:
            # 處理新增和刪除操作
            if operation_type in ['新增', '刪除']:
                return self._process_create_delete(operation_type, old_data, new_data)
            
            # 處理審核操作
            if operation_type == '審核':
                return self._process_audit(old_data, new_data)
            
            # 處理修改操作
            if operation_type == '修改' and new_data:
                # 如果 new_data 包含 message 字段，直接使用它
                if isinstance(new_data, dict) and 'message' in new_data:
                    # 獲取訂單號
                    order_number = None
                    if isinstance(new_data['message'], dict) and 'order_number' in new_data['message']:
                        order_number = new_data['message']['order_number']
                    
                    # 如果有訂單號，嘗試合併同一訂單的變更
                    if order_number:
                        # 如果這個訂單號已經有變更記錄，合併它們
                        if order_number in self._order_changes:
                            existing_changes = self._order_changes[order_number]
                            
                            # 合併產品變更
                            if 'products' in new_data['message'] and 'products' in existing_changes['message']:
                                # 獲取現有產品列表
                                existing_products = existing_changes['message']['products']
                                new_products = new_data['message']['products']
                                
                                # 檢查是否有相同的產品（根據 detail_id 或 name）
                                for new_product in new_products:
                                    # 檢查是否已存在相同的產品
                                    found = False
                                    for existing_product in existing_products:
                                        # 使用 detail_id 或 name 作為唯一標識
                                        if ('detail_id' in new_product and 'detail_id' in existing_product and 
                                            new_product['detail_id'] == existing_product['detail_id']):
                                            # 合併變更
                                            if 'changes' in new_product and 'changes' in existing_product:
                                                existing_product['changes'].update(new_product['changes'])
                                            found = True
                                            break
                                        elif ('name' in new_product and 'name' in existing_product and 
                                              new_product['name'] == existing_product['name']):
                                            # 合併變更
                                            if 'changes' in new_product and 'changes' in existing_product:
                                                existing_product['changes'].update(new_product['changes'])
                                            found = True
                                            break
                                    
                                    # 如果沒有找到相同的產品，添加到列表中
                                    if not found:
                                        existing_products.append(new_product)
                                
                                # 更新時間戳，表示這個訂單的變更已經更新
                                import time
                                self._last_log_time[order_number] = time.time()
                                
                                # 返回合併後的變更記錄，包含完整的產品變更信息
                                return {
                                    'message': {
                                        'order_number': order_number,
                                        'products': existing_products
                                    },
                                    'operation_type': operation_type
                                }
                        else:
                            # 如果這是這個訂單的第一個變更，保存它
                            self._order_changes[order_number] = new_data
                            import time
                            self._last_log_time[order_number] = time.time()
                    
                    # 清理過期的訂單變更（超過5秒的）
                    self._clean_expired_changes()
                    
                    # 確保返回的數據包含 operation_type
                    if 'operation_type' not in new_data:
                        new_data['operation_type'] = operation_type
                    
                    # 返回原始的 new_data
                    return new_data
                
                # 如果沒有 message 字段，嘗試處理更新操作
                if old_data:
                    return self._process_update(old_data, new_data)
                else:
                    # 如果沒有 old_data，但有 new_data 和 operation_type，創建一個基本的變更記錄
                    return {
                        'message': new_data.get('message', {'products': []}),
                        'operation_type': operation_type
                    }
        except Exception as e:
            print(f"Error processing changes: {str(e)}")
            return {'message': '處理變更時發生錯誤', 'operation_type': None}
        
        return {'message': '無變更', 'operation_type': None}

    def _clean_expired_changes(self):
        """清理過期的訂單變更（超過5秒的）"""
        import time
        current_time = time.time()
        expired_orders = []
        
        # 找出過期的訂單
        for order_number, last_time in self._last_log_time.items():
            if current_time - last_time > 5:  # 5秒過期
                expired_orders.append(order_number)
        
        # 刪除過期的訂單變更
        for order_number in expired_orders:
            if order_number in self._order_changes:
                del self._order_changes[order_number]
            if order_number in self._last_log_time:
                del self._last_log_time[order_number]

    def _process_create_delete(self, operation_type: str, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """處理新增和刪除操作"""
        try:
            data = new_data if operation_type == '新增' else old_data
            if isinstance(data, dict) and 'message' in data:
                message = data['message']
                # 如果 message 是 JSON 字符串，先解析它
                if isinstance(message, str):
                    try:
                        message = json.loads(message)
                    except json.JSONDecodeError:
                        print("Failed to parse JSON message")
                        return {'message': '無變更', 'operation_type': None}
                
                if isinstance(message, dict):
                    # 確保返回的格式與原始格式一致
                    return {
                        'message': {
                            'status': message.get('status', '待確認'),
                            'products': message.get('products', []),
                            'order_number': message.get('order_number', '')
                        },
                        'operation_type': operation_type
                    }
            
        except Exception as e:
            print(f"Error in _process_create_delete: {str(e)}")
        return {'message': '無變更', 'operation_type': None}
    
    def _process_audit(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """處理審核操作"""
        try:
            # 如果新數據是字典格式且包含完整的審核信息
            if isinstance(new_data, dict) and isinstance(new_data.get('message'), dict):
                message = new_data['message']
                
                # 從新數據中獲取狀態變更信息
                if 'status' in message and isinstance(message['status'], dict):
                    # 如果已經包含了完整的狀態變更信息，直接使用
                    return {
                        'message': {
                            'order_number': message.get('order_number', ''),
                            'status': message['status']
                        },
                        'operation_type': '審核'
                    }
                else:
                    # 從舊數據中獲取之前的狀態
                    old_status = '待確認'
                    if isinstance(old_data, dict) and isinstance(old_data.get('message'), str):
                        parts = old_data['message'].split('、')
                        for part in parts:
                            if '狀態:' in part:
                                old_status = part.split(':', 1)[1].strip()
                                break
                    
                    # 從新數據中獲取當前狀態
                    new_status = message.get('status', '已確認')
                    if isinstance(new_status, str):
                        return {
                            'message': {
                                'order_number': message.get('order_number', ''),
                                'status': {
                                    'before': old_status,
                                    'after': new_status
                                }
                            },
                            'operation_type': '審核'
                        }
            
            # 如果是舊格式的字符串消息
            if isinstance(old_data, dict) and isinstance(old_data.get('message'), str):
                order_number = ''
                old_status = '待確認'
                parts = old_data['message'].split('、')
                for part in parts:
                    if '訂單號:' in part:
                        order_number = part.split(':', 1)[1].strip()
                    elif '狀態:' in part:
                        old_status = part.split(':', 1)[1].strip()
                
                # 從新數據中獲取目標狀態
                new_status = '已確認'
                if isinstance(new_data, dict) and isinstance(new_data.get('message'), dict):
                    if 'status' in new_data['message']:
                        if isinstance(new_data['message']['status'], dict):
                            new_status = new_data['message']['status'].get('after', '已確認')
                        else:
                            new_status = new_data['message']['status']
                
                return {
                    'message': {
                        'order_number': order_number,
                        'status': {
                            'before': old_status,
                            'after': new_status
                        }
                    },
                    'operation_type': '審核'
                }
            
            return {'message': '無變更', 'operation_type': None}
            
        except Exception as e:
            print(f"Error in _process_audit: {str(e)}")
            return {'message': '無變更', 'operation_type': None}

    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理修改操作"""
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
                    'shipping_date': old_parts.get('出貨日期', ''),  # 改為空字符串
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
                    'shipping_date': new_parts.get('出貨日期', ''),  # 改為空字符串
                    'remark': new_parts.get('備註', '-'),
                    'supplier_note': new_parts.get('供應商備註', '-')
                }]
            }

        try:
            products_changes = []
            status_changes = {}  # 用於記錄狀態變更

            # 比較產品變更
            for i, new_product in enumerate(new_message.get('products', [])):
                changes = {}
                # 獲取對應的舊產品，如果索引超出範圍則使用空字典
                old_product = old_message.get('products', [])[i] if i < len(old_message.get('products', [])) else {}

                # 比較數量
                if old_product.get('quantity', '') != new_product.get('quantity', ''):
                    changes['quantity'] = {
                        'before': old_product.get('quantity', ''),
                        'after': new_product.get('quantity', '')
                    }

                # 比較出貨日期
                old_shipping_date = old_product.get('shipping_date', '')
                new_shipping_date = new_product.get('shipping_date', '')
                if old_shipping_date != new_shipping_date:
                    changes['shipping_date'] = {
                        'before': old_shipping_date,  # 直接使用原始值
                        'after': new_shipping_date    # 直接使用原始值
                    }

                # 比較客戶備註
                if old_product.get('remark', '') != new_product.get('remark', ''):
                    changes['remark'] = {
                        'before': old_product.get('remark', '-'),
                        'after': new_product.get('remark', '-')
                    }

                # 比較供應商備註
                if old_product.get('supplier_note', '') != new_product.get('supplier_note', ''):
                    changes['supplier_note'] = {
                        'before': old_product.get('supplier_note', '-'),
                        'after': new_product.get('supplier_note', '-')
                    }

                # 比較狀態變更
                old_status = old_product.get('status', '')
                new_status = new_product.get('status', '')
                if old_status != new_status:
                    status_changes[new_product.get('name', '')] = {
                        'before': old_status,
                        'after': new_status
                    }

                if changes:  # 只有當有變更時才添加到列表
                    products_changes.append({
                        'name': new_product.get('name', ''),
                        'changes': changes
                    })

            # 如果有狀態變更，添加到產品變更中
            if status_changes:
                status_product_changes = []
                for product_name, status_change in status_changes.items():
                    status_product_changes.append({
                        'name': product_name,
                        'changes': {'status': status_change}
                    })
                # 合併狀態變更和其他變更
                if products_changes:
                    # 更新現有產品的變更
                    for product in products_changes:
                        if product['name'] in status_changes:
                            product['changes']['status'] = status_changes[product['name']]
                else:
                    products_changes = status_product_changes

            if products_changes:  # 只有當有產品變更時才返回
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

    def log_operation(self, table_name: str, operation_type: str, record_id: int, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], performed_by: int, user_type: str) -> bool:
        """記錄訂單操作日誌，重寫父類方法以處理訂單特殊邏輯"""
        try:
            print(f"Logging operation: {operation_type} on {table_name} with ID {record_id}")
            print(f"Old data: {json.dumps(old_data, ensure_ascii=False) if old_data else None}")
            print(f"New data: {json.dumps(new_data, ensure_ascii=False) if new_data else None}")
            print(f"Performed by: {performed_by}, User type: {user_type}")
            
            # 獲取變更信息
            changes = self._get_changes(old_data, new_data, operation_type)
            
            # 如果有變更信息，使用它來替換 new_data
            if changes and changes.get('message') and changes.get('message') != '無變更':
                new_data = changes
            
            # 使用父類的 log_operation 方法，避免直接訪問 db_connection
            return super().log_operation(table_name, operation_type, record_id, old_data, new_data, performed_by, user_type)
        except Exception as e:
            print(f"Error logging operation: {str(e)}")
            return False 