import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService
import os
from backend.config.database import get_db_connection
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

class ProductLogService(BaseLogService):
    """產品日誌服務類，處理產品相關的日誌邏輯"""
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """根据操作类型获取变更信息"""
        if operation_type == '新增' and new_data:
            # 检查是否是锁定日期的操作
            if new_data.get('record_type') == '锁定日期':
                return self._process_lock_date(new_data)
            else:
                return self._process_create(new_data)
        elif operation_type == '刪除' and old_data:
            # 检查是否是解锁日期的操作
            if old_data.get('record_type') == '锁定日期':
                return self._process_unlock_date(old_data)
            else:
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
    
    def _process_lock_date(self, new_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理锁定日期的日志记录"""
        try:
            locked_date = new_data.get('locked_date', '')
            
            return {
                'message': {
                    'locked_date': {
                        'id': new_data.get('id', ''),
                        'date': locked_date,
                        'action': '鎖定日期'
                    }
                },
                'operation_type': '鎖定日期'
            }
        except Exception as e:
            logger.error("处理锁定日期日志错误: %s", str(e))
            return {
                'message': {
                    'locked_date': {}
                },
                'operation_type': '鎖定日期'
            }
    
    def _process_unlock_date(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理解锁日期的日志记录"""
        try:
            locked_date = old_data.get('locked_date', '')
            
            return {
                'message': {
                    'locked_date': {
                        'id': old_data.get('id', ''),
                        'date': locked_date,
                        'action': '解鎖日期'
                    }
                },
                'operation_type': '解鎖日期'
            }
        except Exception as e:
            logger.error("处理解锁日期日志错误: %s", str(e))
            return {
                'message': {
                    'locked_date': {}
                },
                'operation_type': '解鎖日期'
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
            logger.error("处理产品新增日志错误: %s", str(e))
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
            logger.error("处理产品删除日志错误: %s", str(e))
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
            old_image_url = old_data.get('image_url_original', old_data.get('image_url', ''))
            new_image_url = new_data.get('image_url', '')
            
            # 获取原始文件名，优先使用original_image_filename，其次使用image_original_filename
            old_image_original_filename = old_data.get('original_image_filename', old_data.get('image_original_filename', ''))
            new_image_original_filename = new_data.get('image_original_filename', new_data.get('original_image_filename', ''))
            
            if old_image_url != new_image_url:
                changes['image_url'] = {
                    'before': old_image_original_filename or self._get_friendly_filename(old_image_url, old_image_original_filename),
                    'after': new_image_original_filename or self._get_friendly_filename(new_image_url, new_image_original_filename)
                }
            
            old_dm_url = old_data.get('dm_url_original', old_data.get('dm_url', ''))
            new_dm_url = new_data.get('dm_url', '')
            
            # 获取原始文件名，优先使用original_dm_filename，其次使用dm_original_filename
            old_dm_original_filename = old_data.get('original_dm_filename', old_data.get('dm_original_filename', ''))
            new_dm_original_filename = new_data.get('dm_original_filename', new_data.get('original_dm_filename', ''))
            
            if old_dm_url != new_dm_url:
                changes['dm_url'] = {
                    'before': old_dm_original_filename or self._get_friendly_filename(old_dm_url, old_dm_original_filename),
                    'after': new_dm_original_filename or self._get_friendly_filename(new_dm_url, new_dm_original_filename)
                }
            
            # 检查是否有任何实际变更
            if not changes:
                logger.info("Product update - No changes detected for product_id: %s", new_data.get('id'))
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
            logger.error("处理产品更新日志错误: %s", str(e))
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

def log_lock_date(product_id, admin_id, lock_date):
    """
    記錄產品鎖定日期的日誌
    :param product_id: 產品ID
    :param admin_id: 管理員ID
    :param lock_date: 鎖定日期
    :return: 是否記錄成功
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取產品信息
            cursor.execute("""
                SELECT name FROM products WHERE id = %s
            """, (product_id,))
            product = cursor.fetchone()
            
            if not product:
                return False
            
            # 獲取管理員信息
            cursor.execute("""
                SELECT username FROM admins WHERE id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                return False
            
            # 記錄日誌
            cursor.execute("""
                INSERT INTO product_logs (product_id, admin_id, operation_type, details)
                VALUES (%s, %s, 'lock_date', %s)
            """, (
                product_id,
                admin_id,
                f"管理員 {admin['username']} 將產品 {product['name']} 的訂購截止日期設為 {lock_date}"
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error("处理锁定日期日志错误: %s", str(e))
        return False

def log_unlock_date(product_id, admin_id):
    """
    記錄產品解鎖日期的日誌
    :param product_id: 產品ID
    :param admin_id: 管理員ID
    :return: 是否記錄成功
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取產品信息
            cursor.execute("""
                SELECT name FROM products WHERE id = %s
            """, (product_id,))
            product = cursor.fetchone()
            
            if not product:
                return False
            
            # 獲取管理員信息
            cursor.execute("""
                SELECT username FROM admins WHERE id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                return False
            
            # 記錄日誌
            cursor.execute("""
                INSERT INTO product_logs (product_id, admin_id, operation_type, details)
                VALUES (%s, %s, 'unlock_date', %s)
            """, (
                product_id,
                admin_id,
                f"管理員 {admin['username']} 解除了產品 {product['name']} 的訂購截止日期"
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error("处理解锁日期日志错误: %s", str(e))
        return False

def log_product_add(product_id, admin_id, product_data):
    """
    記錄新增產品的日誌
    :param product_id: 產品ID
    :param admin_id: 管理員ID
    :param product_data: 產品數據
    :return: 是否記錄成功
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取管理員信息
            cursor.execute("""
                SELECT username FROM admins WHERE id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                return False
            
            # 記錄日誌
            cursor.execute("""
                INSERT INTO product_logs (product_id, admin_id, operation_type, details, data)
                VALUES (%s, %s, 'add', %s, %s)
            """, (
                product_id,
                admin_id,
                f"管理員 {admin['username']} 新增了產品 {product_data.get('name')}",
                product_data
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error("处理产品新增日志错误: %s", str(e))
        return False

def log_product_delete(product_id, admin_id):
    """
    記錄刪除產品的日誌
    :param product_id: 產品ID
    :param admin_id: 管理員ID
    :return: 是否記錄成功
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取產品信息
            cursor.execute("""
                SELECT name FROM products WHERE id = %s
            """, (product_id,))
            product = cursor.fetchone()
            
            if not product:
                return False
            
            # 獲取管理員信息
            cursor.execute("""
                SELECT username FROM admins WHERE id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                return False
            
            # 記錄日誌
            cursor.execute("""
                INSERT INTO product_logs (product_id, admin_id, operation_type, details)
                VALUES (%s, %s, 'delete', %s)
            """, (
                product_id,
                admin_id,
                f"管理員 {admin['username']} 刪除了產品 {product['name']}"
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error("处理产品删除日志错误: %s", str(e))
        return False

def log_product_update(product_id, admin_id, old_data, new_data):
    """
    記錄更新產品的日誌
    :param product_id: 產品ID
    :param admin_id: 管理員ID
    :param old_data: 舊的產品數據
    :param new_data: 新的產品數據
    :return: 是否記錄成功
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取管理員信息
            cursor.execute("""
                SELECT username FROM admins WHERE id = %s
            """, (admin_id,))
            admin = cursor.fetchone()
            
            if not admin:
                return False
            
            # 比較變更
            changes = []
            if old_data.get('name') != new_data.get('name'):
                changes.append(f"名稱從 '{old_data.get('name')}' 改為 '{new_data.get('name')}'")
            
            if old_data.get('description') != new_data.get('description'):
                changes.append("修改了描述")
            
            if old_data.get('price') != new_data.get('price'):
                changes.append(f"價格從 {old_data.get('price')} 改為 {new_data.get('price')}")
            
            if old_data.get('unit') != new_data.get('unit'):
                changes.append(f"單位從 '{old_data.get('unit')}' 改為 '{new_data.get('unit')}'")
            
            if old_data.get('min_order_quantity') != new_data.get('min_order_quantity'):
                changes.append(f"最小訂購量從 {old_data.get('min_order_quantity')} 改為 {new_data.get('min_order_quantity')}")
            
            # 比較可見客戶列表
            old_customers = set(old_data.get('viewable_customers', []))
            new_customers = set(new_data.get('viewable_customers', []))
            
            if old_customers != new_customers:
                added = new_customers - old_customers
                removed = old_customers - new_customers
                
                if added:
                    changes.append(f"新增了 {len(added)} 個可見客戶")
                if removed:
                    changes.append(f"移除了 {len(removed)} 個可見客戶")
            
            if not changes:
                logger.info("Product update - No changes detected for product_id: %s", new_data.get('id'))
                return True
            
            # 記錄日誌
            details = f"管理員 {admin['username']} 更新了產品 {new_data.get('name')}：" + "、".join(changes)
            
            cursor.execute("""
                INSERT INTO product_logs (product_id, admin_id, operation_type, details, data)
                VALUES (%s, %s, 'update', %s, %s)
            """, (
                product_id,
                admin_id,
                details,
                {'old': old_data, 'new': new_data}
            ))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error("处理产品更新日志错误: %s", str(e))
        return False 