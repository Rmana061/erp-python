import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService
from ..config.database import get_db_connection  # 导入数据库连接
import psycopg2.extras

class CustomerLogService(BaseLogService):
    """客戶日誌服務類，處理客戶相關的日誌邏輯"""
    
    def _get_product_names(self, product_ids_str: str) -> str:
        """通過產品ID獲取產品名稱
        
        Args:
            product_ids_str: 以逗號分隔的產品ID字符串
            
        Returns:
            以逗號分隔的產品名稱字符串
        """
        if not product_ids_str:
            return ""
            
        try:
            # 將產品ID字符串轉換為列表
            product_ids = [int(pid.strip()) for pid in product_ids_str.split(',') if pid.strip().isdigit()]
            
            if not product_ids:
                return ""
                
            # 連接數據庫
            with get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                
                # 構建查詢
                placeholders = ', '.join(['%s'] * len(product_ids))
                query = f"""
                    SELECT id, name as product_name
                    FROM products
                    WHERE id IN ({placeholders})
                    AND status = 'active'
                """
                
                # 執行查詢
                cursor.execute(query, product_ids)
                products = cursor.fetchall()
            
            # 如果沒有找到產品，返回原始ID
            if not products:
                return product_ids_str
                
            # 構建產品名稱字符串
            product_names = []
            for pid in product_ids:
                product_name = next((p['product_name'] for p in products if p['id'] == pid), str(pid))
                product_names.append(product_name)
                
            return ', '.join(product_names)
            
        except Exception as e:
            print(f"Error getting product names: {str(e)}")
            return product_ids_str  # 發生錯誤時返回原始ID
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理客戶變更的方法"""
        print(f"Processing customer changes - operation_type: {operation_type}")
        
        # 處理新增操作
        if operation_type == '新增' and new_data:
            return self._process_create(new_data)
        
        # 處理刪除操作
        if operation_type == '刪除' and old_data:
            return self._process_delete(old_data)
        
        # 處理修改操作
        if operation_type == '修改' and old_data and new_data:
            return self._process_update(old_data, new_data)
        
        # 添加密码更新操作的特殊处理
        if operation_type == '更新密碼':
            return {
                'message': {
                    'customer_id': new_data.get('record_id', ''),
                    'password_changed': True
                },
                'operation_type': '更新密碼'
            }
        
        return {'message': '無變更', 'operation_type': None}
    
    def _compare_changes(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """比较并记录字段变更"""
        changes = {}
        
        if not old_data or not new_data:
            return changes
            
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
                # 對於可購產品欄位，轉換為產品名稱
                if field == 'viewable_products':
                    old_product_names = self._get_product_names(old_value)
                    new_product_names = self._get_product_names(new_value)
                    changes[field] = {
                        'before': old_product_names,
                        'after': new_product_names,
                        'before_ids': old_value,
                        'after_ids': new_value
                    }
                else:
                    changes[field] = {
                        'before': old_value,
                        'after': new_value
                    }
        
        return changes
    
    def _process_create(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理客戶新增操作"""
        try:
            customer_info = {}
            
            # 從新數據中提取客戶信息 - 完整記錄所有客戶欄位
            if isinstance(new_data, dict):
                # 獲取產品名稱
                viewable_products_ids = new_data.get('viewable_products', '')
                viewable_products_names = self._get_product_names(viewable_products_ids)
                
                customer_info = {
                    'id': new_data.get('id', ''),
                    'username': new_data.get('username', ''),
                    'company_name': new_data.get('company_name', ''),
                    'contact_person': new_data.get('contact_person', ''),
                    'phone': new_data.get('phone', ''),
                    'email': new_data.get('email', ''),
                    'address': new_data.get('address', ''),
                    'line_account': new_data.get('line_account', ''),
                    'viewable_products': viewable_products_names,  # 使用產品名稱
                    'viewable_products_ids': viewable_products_ids,  # 保留原始ID以供參考
                    'remark': new_data.get('remark', '')
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
    
    def _process_delete(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理客戶刪除操作"""
        try:
            customer_info = {}
            
            # 從舊數據中提取客戶信息 - 完整記錄所有客戶欄位
            if isinstance(old_data, dict):
                # 獲取產品名稱
                viewable_products_ids = old_data.get('viewable_products', '')
                viewable_products_names = self._get_product_names(viewable_products_ids)
                
                customer_info = {
                    'id': old_data.get('id', ''),
                    'username': old_data.get('username', ''),
                    'company_name': old_data.get('company_name', ''),
                    'contact_person': old_data.get('contact_person', ''),
                    'phone': old_data.get('phone', ''),
                    'email': old_data.get('email', ''),
                    'address': old_data.get('address', ''),
                    'line_account': old_data.get('line_account', ''),
                    'viewable_products': viewable_products_names,  # 使用產品名稱
                    'viewable_products_ids': viewable_products_ids,  # 保留原始ID以供參考
                    'remark': old_data.get('remark', '')
                }
            
            return {
                'message': {
                    'customer': customer_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            print(f"Error processing customer delete: {str(e)}")
            return {'message': '處理客戶刪除時發生錯誤', 'operation_type': None}
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理客户更新操作，生成适合日志显示的数据格式"""
        try:
            # 检查是否有密码变更标记
            password_changed = new_data.get('password_changed', False)
            
            # 处理常规字段变更
            changes = self._compare_changes(old_data, new_data)
            
            # 如果是密码修改操作，添加明显标记
            if password_changed:
                # 添加特殊字段，方便前端识别
                changes['__password_changed__'] = True
            
            if not changes and not password_changed:
                return {
                    'message': '無變更',
                    'operation_type': None
                }
                
            # 獲取產品名稱用於顯示
            old_products_ids = old_data.get('viewable_products', '')
            new_products_ids = new_data.get('viewable_products', '')
            old_products_names = self._get_product_names(old_products_ids)
            new_products_names = self._get_product_names(new_products_ids)
            
            # 构建返回信息
            message = {
                'customer_id': new_data.get('id', ''),
                'old_data': {
                    'id': old_data.get('id', ''),
                    'username': old_data.get('username', ''),
                    'company_name': old_data.get('company_name', ''),
                    'contact_person': old_data.get('contact_person', ''),
                    'phone': old_data.get('phone', ''),
                    'email': old_data.get('email', ''),
                    'address': old_data.get('address', ''),
                    'line_account': old_data.get('line_account', ''),
                    'viewable_products': old_products_names,
                    'viewable_products_ids': old_products_ids,
                    'remark': old_data.get('remark', '')
                },
                'new_data': {
                    'id': new_data.get('id', ''),
                    'username': new_data.get('username', ''),
                    'company_name': new_data.get('company_name', ''),
                    'contact_person': new_data.get('contact_person', ''),
                    'phone': new_data.get('phone', ''),
                    'email': new_data.get('email', ''),
                    'address': new_data.get('address', ''),
                    'line_account': new_data.get('line_account', ''),
                    'viewable_products': new_products_names,
                    'viewable_products_ids': new_products_ids,
                    'remark': new_data.get('remark', '')
                },
                'changes': changes
            }
            
            # 如果有密码变更，添加明确标记
            if password_changed:
                message['password_changed'] = True
                
            # 确定操作类型 - 同时修改多个字段但包含密码时，也标记为同时包含密码修改
            operation_type = '修改(含密碼)' if password_changed else '修改'
            
            return {
                'message': message,
                'operation_type': operation_type
            }
        except Exception as e:
            print(f"Error processing customer update: {str(e)}")
            return {
                'message': '處理客戶修改時發生錯誤',
                'operation_type': None
            } 