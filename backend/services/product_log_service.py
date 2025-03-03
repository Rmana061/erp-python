import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService

class ProductLogService(BaseLogService):
    """產品日誌服務類，處理產品相關的日誌邏輯"""
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理產品變更的方法"""
        print(f"Processing product changes - operation_type: {operation_type}")
        
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
        """處理產品新增操作"""
        try:
            product_info = {}
            
            # 從新數據中提取產品信息
            if isinstance(new_data, dict):
                product_info = {
                    'id': new_data.get('id', ''),
                    'name': new_data.get('name', ''),
                    'description': new_data.get('description', ''),
                    'price': new_data.get('price', ''),
                    'category': new_data.get('category', ''),
                    'stock': new_data.get('stock', '')
                }
            
            return {
                'message': {
                    'product': product_info
                },
                'operation_type': '新增'
            }
        except Exception as e:
            print(f"Error processing product create: {str(e)}")
            return {'message': '處理產品新增時發生錯誤', 'operation_type': None}
    
    def _process_delete(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理產品刪除操作"""
        try:
            product_info = {}
            
            # 從舊數據中提取產品信息
            if isinstance(old_data, dict):
                product_info = {
                    'id': old_data.get('id', ''),
                    'name': old_data.get('name', ''),
                    'description': old_data.get('description', ''),
                    'price': old_data.get('price', ''),
                    'category': old_data.get('category', '')
                }
            
            return {
                'message': {
                    'product': product_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            print(f"Error processing product delete: {str(e)}")
            return {'message': '處理產品刪除時發生錯誤', 'operation_type': None}
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理產品修改操作"""
        try:
            changes = {}
            
            # 比較並記錄變更
            fields_to_check = ['name', 'description', 'price', 'category', 'stock', 'image_url']
            
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
                        'product_id': new_data.get('id', ''),
                        'product_name': new_data.get('name', ''),
                        'changes': changes
                    },
                    'operation_type': '修改'
                }
            
            return {'message': '無變更', 'operation_type': None}
        except Exception as e:
            print(f"Error processing product update: {str(e)}")
            return {'message': '處理產品修改時發生錯誤', 'operation_type': None} 