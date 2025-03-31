import json
from typing import Dict, Any, Optional
from .base_log_service import BaseLogService
from ..config.database import get_db_connection  # 导入数据库连接
import psycopg2.extras
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

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
            logger.error("獲取產品名稱時發生錯誤: %s", str(e))
            return product_ids_str  # 發生錯誤時返回原始ID
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理客戶變更的方法"""
        logger.debug("處理客戶變更 - 操作類型: %s", operation_type)
        
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
        """比较新旧数据的变更"""
        changes = {}
        
        # 用户名变更
        if old_data.get('username') != new_data.get('username'):
            changes['username'] = {
                'before': old_data.get('username', '-'),
                'after': new_data.get('username', '-')
            }
        
        # 公司名变更
        if old_data.get('company_name') != new_data.get('company_name'):
            changes['company_name'] = {
                'before': old_data.get('company_name', '-'),
                'after': new_data.get('company_name', '-')
            }
        
        # 联系人变更
        if old_data.get('contact_name') != new_data.get('contact_person') and old_data.get('contact_person') != new_data.get('contact_person'):
            old_contact = old_data.get('contact_name') or old_data.get('contact_person', '-')
            changes['contact_person'] = {
                'before': old_contact,
                'after': new_data.get('contact_person', '-')
            }
        
        # 电话变更
        if old_data.get('phone') != new_data.get('phone'):
            changes['phone'] = {
                'before': old_data.get('phone', '-'),
                'after': new_data.get('phone', '-')
            }
        
        # 邮箱变更
        if old_data.get('email') != new_data.get('email'):
            changes['email'] = {
                'before': old_data.get('email', '-'),
                'after': new_data.get('email', '-')
            }
        
        # 地址变更
        if old_data.get('address') != new_data.get('address'):
            changes['address'] = {
                'before': old_data.get('address', '-'),
                'after': new_data.get('address', '-')
            }
    
        
        # 可见产品变更
        if old_data.get('viewable_products') != new_data.get('viewable_products'):
            old_products = self._get_product_names(old_data.get('viewable_products', ''))
            new_products = self._get_product_names(new_data.get('viewable_products', ''))
            
            changes['viewable_products'] = {
                'before': old_products or '-',
                'after': new_products or '-'
            }
            
        # 备注变更
        if old_data.get('remark') != new_data.get('remark'):
            changes['remark'] = {
                'before': old_data.get('remark', '-'),
                'after': new_data.get('remark', '-')
            }
            
        # 重复下单限制天数变更
        if old_data.get('reorder_limit_days') != new_data.get('reorder_limit_days'):
            old_limit = old_data.get('reorder_limit_days')
            new_limit = new_data.get('reorder_limit_days')
            old_display = f"{old_limit}天" if old_limit and old_limit > 0 else "無限制"
            new_display = f"{new_limit}天" if new_limit and new_limit > 0 else "無限制"
            
            changes['reorder_limit_days'] = {
                'before': old_display,
                'after': new_display
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
                
                # 處理LINE帳號信息 - 新的多帳號結構
                line_users = new_data.get('line_users', [])
                line_groups = new_data.get('line_groups', [])
                
                customer_info = {
                    'id': new_data.get('id', ''),
                    'username': new_data.get('username', ''),
                    'company_name': new_data.get('company_name', ''),
                    'contact_person': new_data.get('contact_person', ''),
                    'phone': new_data.get('phone', ''),
                    'email': new_data.get('email', ''),
                    'address': new_data.get('address', ''),
                    'line_users': line_users,
                    'line_groups': line_groups,
                    'viewable_products': viewable_products_names,  # 使用產品名稱
                    'viewable_products_ids': viewable_products_ids,  # 保留原始ID以供參考
                    'remark': new_data.get('remark', ''),
                    'reorder_limit_days': new_data.get('reorder_limit_days', 0)
                }
            
            return {
                'message': {
                    'customer': customer_info
                },
                'operation_type': '新增'
            }
        except Exception as e:
            logger.error("處理客戶新增時發生錯誤: %s", str(e))
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
                
                # 處理LINE帳號信息 - 新的多帳號結構
                line_users = old_data.get('line_users', [])
                line_groups = old_data.get('line_groups', [])
                
                customer_info = {
                    'id': old_data.get('id', ''),
                    'username': old_data.get('username', ''),
                    'company_name': old_data.get('company_name', ''),
                    'contact_person': old_data.get('contact_person', ''),
                    'phone': old_data.get('phone', ''),
                    'email': old_data.get('email', ''),
                    'address': old_data.get('address', ''),
                    'line_users': line_users,
                    'line_groups': line_groups,
                    'viewable_products': viewable_products_names,  # 使用產品名稱
                    'viewable_products_ids': viewable_products_ids,  # 保留原始ID以供參考
                    'remark': old_data.get('remark', ''),
                    'reorder_limit_days': old_data.get('reorder_limit_days', 0)
                }
            
            return {
                'message': {
                    'customer': customer_info
                },
                'operation_type': '刪除'
            }
        except Exception as e:
            logger.error("處理客戶刪除時發生錯誤: %s", str(e))
            return {'message': '處理客戶刪除時發生錯誤', 'operation_type': None}
    
    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理客户更新操作，生成适合日志显示的数据格式"""
        try:
            # 检查是否有密码变更标记
            password_changed = new_data.get('password_changed', False)
            
            # 处理常规字段变更
            changes = self._compare_changes(old_data, new_data)
            
            # 检查是否有LINE账号变更
            has_line_changes = False
            line_changes = new_data.get('line_changes')
            
            if line_changes:
                logger.debug("檢測到客戶ID %s 的LINE變更", new_data.get('id'))
                # 将LINE变更信息合并到changes中
                if isinstance(line_changes, dict):
                    if 'line_users' in line_changes:
                        # 簡化顯示，只保留用戶名稱
                        changes['line_users'] = line_changes['line_users']
                        has_line_changes = True
                    
                    if 'line_groups' in line_changes:
                        # 簡化顯示，只保留群組名稱
                        changes['line_groups'] = line_changes['line_groups']
                        has_line_changes = True
                        
                    if 'line_account' in line_changes:
                        # LINE帳號顯示使用名稱代替ID
                        changes['line_account'] = {
                            'before': line_changes['line_account'].get('before', ''),
                            'after': line_changes['line_account'].get('after', '')
                        }
                        has_line_changes = True
            
            # 如果是密码修改操作，添加明显标记
            if password_changed:
                # 添加特殊字段，方便前端识别
                changes['__password_changed__'] = True
                changes['password'] = {
                    'before': '********',
                    'after': '********（已更新）'
                }
            
            if not changes and not password_changed and not has_line_changes:
                logger.info("客戶更新 - 未檢測到變更，客戶ID: %s", new_data.get('id'))
                return None
            
            # 即使只有密碼變更，也要產生記錄
            if password_changed and len(changes) <= 1:  # 只有密碼變更或許多__password_changed__標記
                logger.debug("客戶密碼已更改，客戶ID: %s", new_data.get('id'))
                changes['password'] = {
                    'before': '********',
                    'after': '********（已更新）'
                }
            
            # 獲取產品名稱用於顯示
            old_products_ids = old_data.get('viewable_products', '')
            new_products_ids = new_data.get('viewable_products', '')
            old_products_names = self._get_product_names(old_products_ids)
            new_products_names = self._get_product_names(new_products_ids)
            
            customer_info = {
                'id': new_data.get('id', ''),
                'username': new_data.get('username', ''),
                'company_name': new_data.get('company_name', ''),
                'old_viewable_products': old_products_names,
                'new_viewable_products': new_products_names,
                'changes': changes
            }
            
            # 如果有LINE变更，添加更多详细信息
            if has_line_changes:
                # 添加LINE用户和群组信息供前端显示
                customer_info['old_line_users'] = old_data.get('line_users', [])
                customer_info['new_line_users'] = new_data.get('line_users', [])
                customer_info['old_line_groups'] = old_data.get('line_groups', [])
                customer_info['new_line_groups'] = new_data.get('line_groups', [])
            
            return {
                'message': {
                    'customer': customer_info
                },
                'operation_type': '修改'
            }
        except Exception as e:
            logger.error("客戶更新日誌處理錯誤: %s", str(e))
            import traceback
            traceback.print_exc()
            return None 