import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService
import os

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
                'image_url': self._get_friendly_filename(new_data.get('image_url', ''), new_data.get('image_original_filename', '')),
                'dm_url': self._get_friendly_filename(new_data.get('dm_url', ''), new_data.get('dm_original_filename', '')),
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
                'image_url': self._get_friendly_filename(old_data.get('image_url', ''), old_data.get('image_original_filename', old_data.get('original_image_filename', ''))),
                'dm_url': self._get_friendly_filename(old_data.get('dm_url', ''), old_data.get('dm_original_filename', old_data.get('original_dm_filename', ''))),
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
                'name', 'description', 'min_order_qty', 
                'max_order_qty', 'product_unit', 'special_date', 'status'
            ]
            
            # 处理常规字段
            for field in fields_to_check:
                old_value = old_data.get(field)
                new_value = new_data.get(field)
                
                # 确保类型一致性比较
                if isinstance(old_value, str) and not isinstance(new_value, str):
                    new_value = str(new_value)
                elif isinstance(new_value, str) and not isinstance(old_value, str):
                    old_value = str(old_value)
                
                if old_value != new_value and (old_value is not None and new_value is not None):
                    changes[field] = {
                        'before': old_value,
                        'after': new_value
                    }
            
            # 特殊处理出货天数字段，确保类型一致
            old_shipping_time = old_data.get('shipping_time')
            new_shipping_time = new_data.get('shipping_time')
            
            # 将两者都转换为整数进行比较
            try:
                old_shipping_time_int = int(old_shipping_time) if old_shipping_time not in (None, '') else 0
                new_shipping_time_int = int(new_shipping_time) if new_shipping_time not in (None, '') else 0
                
                if old_shipping_time_int != new_shipping_time_int:
                    changes['shipping_time'] = {
                        'before': old_shipping_time,
                        'after': new_shipping_time
                    }
            except (ValueError, TypeError):
                # 如果转换失败，使用原始值比较
                if str(old_shipping_time) != str(new_shipping_time):
                    changes['shipping_time'] = {
                        'before': old_shipping_time,
                        'after': new_shipping_time
                    }
            
            # 特殊处理图片和文档URL
            old_image_url = old_data.get('image_url', '')
            new_image_url = new_data.get('image_url', '')
            
            if old_image_url != new_image_url:
                changes['image_url'] = {
                    'before': self._get_friendly_filename(old_image_url, old_data.get('original_image_filename', '')),
                    'after': self._get_friendly_filename(new_image_url, new_data.get('image_original_filename', ''))
                }
            
            old_dm_url = old_data.get('dm_url', '')
            new_dm_url = new_data.get('dm_url', '')
            
            if old_dm_url != new_dm_url:
                changes['dm_url'] = {
                    'before': self._get_friendly_filename(old_dm_url, old_data.get('original_dm_filename', '')),
                    'after': self._get_friendly_filename(new_dm_url, new_data.get('dm_original_filename', ''))
                }
            
            # 检查是否有任何实际变更
            if not changes:
                print(f"Product update - No changes detected for product_id: {new_data.get('id')}")
                return None
            
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
            return None
    
    def _get_friendly_filename(self, file_url, original_filename):
        """获取友好的文件名显示"""
        if not file_url:
            return ""
        
        # 如果有原始文件名，直接使用
        if original_filename:
            return original_filename
        
        # 否则尝试从URL中提取文件名
        filename = os.path.basename(file_url)
        return filename 