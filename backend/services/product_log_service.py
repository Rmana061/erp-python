import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService

class ProductLogService(BaseLogService):
    """產品日誌服務類，處理產品相關的日誌邏輯"""
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """根据操作类型获取变更信息"""
        if operation_type == '新增' and new_data:
            return self._process_create(new_data)
        elif operation_type == '刪除' and old_data:
            return self._process_delete(old_data)
        elif operation_type == '修改' and old_data and new_data:
            return self._process_update(old_data, new_data)
        else:
            # 默认返回空消息
            return {
                'message': {
                    'product': {}
                },
                'operation_type': operation_type or '未知'
            }
    
    def _process_create(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理產品新增的日誌記錄"""
        try:
            # 构建产品信息
            product_info = {
                'id': new_data.get('id', ''),
                'name': new_data.get('name', ''),
                'description': new_data.get('description', ''),
                'image_url': new_data.get('image_url', ''),
                'dm_url': new_data.get('dm_url', ''),
                'min_order_qty': new_data.get('min_order_qty', 0),
                'max_order_qty': new_data.get('max_order_qty', 0),
                'product_unit': new_data.get('product_unit', ''),
                'shipping_time': new_data.get('shipping_time', 0),
                'special_date': new_data.get('special_date', False)
            }
            
            # 返回格式化的消息
            return {
                'message': {
                    'product': product_info
                },
                'operation_type': '新增'
            }
        except Exception as e:
            print(f"处理产品新增日志错误: {str(e)}")
            return {
                'message': {
                    'product': {}
                },
                'operation_type': '新增'
            }
    
    def _process_delete(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理產品刪除的日誌記錄"""
        try:
            # 构建产品信息
            product_info = {
                'id': old_data.get('id', ''),
                'name': old_data.get('name', ''),
                'description': old_data.get('description', ''),
                'image_url': old_data.get('image_url', ''),
                'dm_url': old_data.get('dm_url', ''),
                'min_order_qty': old_data.get('min_order_qty', 0),
                'max_order_qty': old_data.get('max_order_qty', 0),
                'product_unit': old_data.get('product_unit', ''),
                'shipping_time': old_data.get('shipping_time', 0),
                'special_date': old_data.get('special_date', False)
            }
            
            # 返回格式化的消息
            return {
                'message': {
                    'product': product_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            print(f"处理产品删除日志错误: {str(e)}")
            return {
                'message': {
                    'product': {}
                },
                'operation_type': '刪除'
            }
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理產品更新的日誌記錄"""
        try:
            # 构建变更信息
            changes = {}
            
            # 检查各字段是否有变更
            fields_to_check = [
                'name', 'description', 'image_url', 'dm_url', 
                'min_order_qty', 'max_order_qty', 'product_unit', 
                'shipping_time', 'special_date', 'status'
            ]
            
            for field in fields_to_check:
                old_value = old_data.get(field)
                new_value = new_data.get(field)
                
                if old_value != new_value:
                    changes[field] = {
                        'before': old_value,
                        'after': new_value
                    }
            
            # 构建产品信息
            product_info = {
                'id': new_data.get('id', old_data.get('id', '')),
                'name': new_data.get('name', old_data.get('name', '')),
                'changes': changes
            }
            
            # 返回格式化的消息
            return {
                'message': {
                    'product': product_info
                },
                'operation_type': '修改'
            }
        except Exception as e:
            print(f"处理产品更新日志错误: {str(e)}")
            return {
                'message': {
                    'product': {}
                },
                'operation_type': '修改'
            } 