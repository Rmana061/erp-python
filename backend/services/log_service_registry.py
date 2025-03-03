from .base_log_service import BaseLogService
from .order_log_service import OrderLogService
from .customer_log_service import CustomerLogService
from .product_log_service import ProductLogService
from .admin_log_service import AdminLogService

class LogServiceRegistry:
    """日誌服務註冊表，用於獲取適當的日誌服務實例"""
    
    @staticmethod
    def get_service(db_connection, table_name=None):
        """根據表名獲取適當的日誌服務實例"""
        if table_name == 'orders' or table_name == 'order_details':
            return OrderLogService(db_connection)
        elif table_name == 'customers':
            return CustomerLogService(db_connection)
        elif table_name == 'products':
            return ProductLogService(db_connection)
        elif table_name == 'administrators':
            return AdminLogService(db_connection)
        else:
            # 返回基礎日誌服務
            return BaseLogService(db_connection) 