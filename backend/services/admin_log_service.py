import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService

class AdminLogService(BaseLogService):
    """管理員日誌服務類，處理管理員相關的日誌邏輯"""
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理管理員變更的方法"""
        print(f"Processing admin changes - operation_type: {operation_type}")
        
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
        """處理管理員新增操作"""
        try:
            admin_info = {}
            
            # 從新數據中提取管理員信息
            if isinstance(new_data, dict):
                admin_info = {
                    'id': new_data.get('id', ''),
                    'username': new_data.get('username', ''),
                    'email': new_data.get('email', ''),
                    'role': new_data.get('role', '')
                }
                
                # 不記錄密碼信息
                if 'password' in admin_info:
                    del admin_info['password']
            
            return {
                'message': {
                    'admin': admin_info
                },
                'operation_type': '新增'
            }
        except Exception as e:
            print(f"Error processing admin create: {str(e)}")
            return {'message': '處理管理員新增時發生錯誤', 'operation_type': None}
    
    def _process_delete(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理管理員刪除操作"""
        try:
            admin_info = {}
            
            # 從舊數據中提取管理員信息
            if isinstance(old_data, dict):
                admin_info = {
                    'id': old_data.get('id', ''),
                    'username': old_data.get('username', ''),
                    'email': old_data.get('email', ''),
                    'role': old_data.get('role', '')
                }
                
                # 不記錄密碼信息
                if 'password' in admin_info:
                    del admin_info['password']
            
            return {
                'message': {
                    'admin': admin_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            print(f"Error processing admin delete: {str(e)}")
            return {'message': '處理管理員刪除時發生錯誤', 'operation_type': None}
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理管理員修改操作"""
        try:
            changes = {}
            
            # 比較並記錄變更
            fields_to_check = ['username', 'email', 'role', 'status']
            
            for field in fields_to_check:
                old_value = old_data.get(field, '')
                new_value = new_data.get(field, '')
                
                if old_value != new_value:
                    changes[field] = {
                        'before': old_value,
                        'after': new_value
                    }
            
            # 特殊處理密碼變更
            if 'password' in new_data and 'password' in old_data and old_data['password'] != new_data['password']:
                changes['password'] = {
                    'before': '******',
                    'after': '******'  # 不顯示實際密碼，只標記有變更
                }
            
            if changes:
                return {
                    'message': {
                        'admin_id': new_data.get('id', ''),
                        'admin_username': new_data.get('username', ''),
                        'changes': changes
                    },
                    'operation_type': '修改'
                }
            
            return {'message': '無變更', 'operation_type': None}
        except Exception as e:
            print(f"Error processing admin update: {str(e)}")
            return {'message': '處理管理員修改時發生錯誤', 'operation_type': None} 