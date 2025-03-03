import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService

class CustomerLogService(BaseLogService):
    """客戶日誌服務類，處理客戶相關的日誌邏輯"""
    
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
        
        return {'message': '無變更', 'operation_type': None}
    
    def _process_create(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理客戶新增操作"""
        try:
            customer_info = {}
            
            # 從新數據中提取客戶信息
            if isinstance(new_data, dict):
                customer_info = {
                    'id': new_data.get('id', ''),
                    'name': new_data.get('name', ''),
                    'email': new_data.get('email', ''),
                    'phone': new_data.get('phone', ''),
                    'address': new_data.get('address', ''),
                    'company': new_data.get('company', '')
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
            
            # 從舊數據中提取客戶信息
            if isinstance(old_data, dict):
                customer_info = {
                    'id': old_data.get('id', ''),
                    'name': old_data.get('name', ''),
                    'email': old_data.get('email', ''),
                    'phone': old_data.get('phone', ''),
                    'company': old_data.get('company', '')
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
        """處理客戶修改操作"""
        try:
            changes = {}
            
            # 比較並記錄變更
            fields_to_check = ['name', 'email', 'phone', 'address', 'company']
            
            for field in fields_to_check:
                old_value = old_data.get(field, '')
                new_value = new_data.get(field, '')
                
                if old_value != new_value:
                    changes[field] = {
                        'before': old_value,
                        'after': new_value
                    }
            
            if changes:
                return {
                    'message': {
                        'customer_id': new_data.get('id', ''),
                        'customer_name': new_data.get('name', ''),
                        'changes': changes
                    },
                    'operation_type': '修改'
                }
            
            return {'message': '無變更', 'operation_type': None}
        except Exception as e:
            print(f"Error processing customer update: {str(e)}")
            return {'message': '處理客戶修改時發生錯誤', 'operation_type': None} 