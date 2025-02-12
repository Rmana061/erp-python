from backend.config.database import get_db_connection
import psycopg2.extras

class Admin:
    @staticmethod
    def get_by_id(admin_id):
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("""
                SELECT a.*, p.*
                FROM administrators a
                JOIN permission_levels p ON a.permission_level_id = p.id
                WHERE a.id = %s AND a.status = 'active'
            """, (admin_id,))
            admin = cursor.fetchone()
            if admin:
                # 將數據庫中的整數值轉換為布爾值
                permissions = {
                    'can_approve_orders': admin['can_approve_orders'] == 1,
                    'can_edit_orders': admin['can_edit_orders'] == 1,
                    'can_close_order_dates': admin['can_close_order_dates'] == 1,
                    'can_add_customer': admin['can_add_customer'] == 1,
                    'can_add_product': admin['can_add_product'] == 1,
                    'can_add_personnel': admin['can_add_personnel'] == 1,
                    'can_view_system_logs': admin['can_view_system_logs'] == 1,
                    'can_decide_product_view': admin['can_decide_product_view'] == 1
                }
                return {
                    'id': admin['id'],
                    'admin_account': admin['admin_account'],
                    'admin_name': admin['admin_name'],
                    'staff_no': admin['staff_no'],
                    'permission_level_id': admin['permission_level_id'],
                    'permissions': permissions
                }
            return None 