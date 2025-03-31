import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

class AdminLogService(BaseLogService):
    """管理員日誌服務類，處理管理員相關的日誌邏輯"""
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理管理員變更的方法"""
        logger.debug("處理管理員變更 - 操作類型: %s", operation_type)
        
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
            # 從新數據中提取管理員信息
            if isinstance(new_data, dict):
                admin_info = {
                    'admin_account': new_data.get('admin_account', ''),
                    'admin_name': new_data.get('admin_name', ''),
                    'staff_no': new_data.get('staff_no', ''),
                    'permission_level': new_data.get('permission_level', '')
                }
            
            return {
                'message': {
                    'admin': admin_info
                },
                'operation_type': '新增'
            }
        except Exception as e:
            logger.error("處理管理員新增時發生錯誤: %s", str(e))
            return {'message': '處理管理員新增時發生錯誤', 'operation_type': None}
    
    def _process_delete(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理管理員刪除操作"""
        try:
            # 從舊數據中提取管理員信息
            if isinstance(old_data, dict):
                admin_info = {
                    'admin_account': old_data.get('admin_account', ''),
                    'admin_name': old_data.get('admin_name', ''),
                    'staff_no': old_data.get('staff_no', ''),
                    'permission_level': old_data.get('permission_level', '')
                }
            
            return {
                'message': {
                    'admin': admin_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            logger.error("處理管理員刪除時發生錯誤: %s", str(e))
            return {'message': '處理管理員刪除時發生錯誤', 'operation_type': None}
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理管理員修改操作"""
        try:
            changes = {}
            
            # 比較並記錄變更
            fields_to_check = ['admin_account', 'admin_name', 'staff_no', 'permission_level_id']
            field_display_names = {
                'admin_account': '人員帳號',
                'admin_name': '人員姓名',
                'staff_no': '人員工號',
                'permission_level_id': '人員權限'
            }
            
            for field in fields_to_check:
                old_value = old_data.get(field, '')
                new_value = new_data.get(field, '')
                
                if old_value != new_value:
                    display_field = field_display_names.get(field, field)
                    changes[display_field] = {
                        'before': old_value,
                        'after': new_value
                    }
            
            # 特殊處理密碼變更
            password_changed = False
            if 'admin_password' in new_data and new_data['admin_password']:
                # 检查密码是否确实发生了变化（不是提交空密码）
                if new_data['admin_password'].strip():
                    password_changed = True
                    changes['人員密碼'] = {
                        'before': '******',
                        'after': '已更新密碼'  # 只提示密碼已更新，不顯示實際密碼
                    }
            
            if not changes and not password_changed:
                logger.info("管理員更新 - 未檢測到變更，管理員ID: %s", new_data.get('id'))
                return None
                
            admin_info = {
                'admin_account': new_data.get('admin_account', ''),
                'admin_name': new_data.get('admin_name', ''),
                'staff_no': new_data.get('staff_no', ''),
                'permission_level': new_data.get('permission_level', '')
            }
            
            return {
                'message': {
                    'admin': admin_info,
                    'changes': changes
                },
                'operation_type': '修改'
            }
        except Exception as e:
            logger.error("處理管理員更新時發生錯誤: %s", str(e))
            return None 