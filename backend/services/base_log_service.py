import json
from datetime import datetime
from typing import Dict, Any, Optional

class BaseLogService:
    """基礎日誌服務類，提供共享的日誌邏輯"""
    
    def __init__(self, db_connection):
        self.conn = db_connection
    
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """基礎變更計算方法，子類應該重寫此方法"""
        return {'message': '無變更', 'operation_type': None}

    def log_operation(self, table_name: str, operation_type: str, record_id: int, 
                     old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]],
                     performed_by: int, user_type: str) -> bool:
        """記錄操作日誌"""
        try:
            print(f"Received log operation request:")
            print(f"Table: {table_name}")
            print(f"Operation: {operation_type}")
            print(f"Record ID: {record_id}")

            # 序列化日期時間
            def serialize_datetime(obj):
                if isinstance(obj, datetime):
                    return obj.strftime('%Y-%m-%d %H:%M:%S')
                return obj

            # 序列化數據
            if old_data:
                old_data = json.loads(json.dumps(old_data, default=serialize_datetime, ensure_ascii=False))
            if new_data:
                new_data = json.loads(json.dumps(new_data, default=serialize_datetime, ensure_ascii=False))

            print(f"New data: {json.dumps(new_data, ensure_ascii=False)}")
            print(f"Performed by: {performed_by}")
            print(f"User type: {user_type}")

            cursor = self.conn.cursor()
            
            # 計算變更詳情
            operation_detail = self._get_changes(old_data, new_data, operation_type)
            
            # 如果operation_detail中沒有operation_type，使用傳入的operation_type
            if operation_detail and 'operation_type' not in operation_detail:
                operation_detail['operation_type'] = operation_type
            
            # 插入日誌記錄
            if operation_detail:
                # 確保有operation_type，即使是None也要插入記錄
                cursor.execute("""
                    INSERT INTO logs 
                    (table_name, operation_type, record_id, operation_detail, 
                     performed_by, user_type, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, NOW())
                """, (
                    table_name,
                    operation_type,
                    record_id,
                    json.dumps(operation_detail, ensure_ascii=False),
                    performed_by,
                    user_type
                ))
                self.conn.commit()
                print(f"日志记录成功: {operation_type} - {table_name} - ID: {record_id}")
                return True
            
            print(f"Failed to log {operation_type} operation")
            return False

        except Exception as e:
            print(f"Error logging operation: {str(e)}")
            self.conn.rollback()
            return False

    def get_logs(self,
                table_name: Optional[str] = None,
                operation_type: Optional[str] = None,
                start_date: Optional[str] = None,
                end_date: Optional[str] = None,
                user_type: Optional[str] = None,
                performed_by: Optional[int] = None,
                record_detail: Optional[str] = None,
                limit: int = 100,
                offset: int = 0) -> tuple:
        """獲取並分頁日誌記錄"""
        try:
            cursor = self.conn.cursor()

            # 構建查詢條件
            conditions = []
            params = []

            if table_name:
                conditions.append("l.table_name = %s")
                params.append(table_name)

            if operation_type:
                conditions.append("l.operation_type = %s")
                params.append(operation_type)

            if start_date:
                conditions.append("DATE(l.created_at) >= %s")
                params.append(start_date)

            if end_date:
                conditions.append("DATE(l.created_at) <= %s")
                params.append(end_date)

            if user_type:
                conditions.append("l.user_type = %s")
                params.append(user_type)

            if performed_by:
                conditions.append("l.performed_by = %s")
                params.append(performed_by)
                
            if record_detail:
                conditions.append("""
                    (
                        CASE
                            WHEN l.table_name = 'orders' THEN COALESCE(o.order_number, CAST(l.record_id AS TEXT))
                            WHEN l.table_name = 'products' THEN COALESCE(p.name, CAST(l.record_id AS TEXT))
                            WHEN l.table_name = 'customers' THEN COALESCE(c.company_name, CAST(l.record_id AS TEXT))
                            WHEN l.table_name = 'administrators' THEN COALESCE(a.staff_no, CAST(l.record_id AS TEXT))
                            ELSE CAST(l.record_id AS TEXT)
                        END ILIKE %s
                        OR (l.operation_detail)::text ILIKE %s
                    )
                """)
                like_pattern = f'%{record_detail}%'
                params.append(like_pattern)
                params.append(like_pattern)

            # 構建 WHERE 子句
            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # 計算總數量
            count_query = f"""
                SELECT COUNT(*) 
                FROM logs l
                LEFT JOIN administrators a ON l.performed_by = a.id AND l.user_type = '管理員'
                LEFT JOIN customers c ON l.performed_by = c.id AND l.user_type = '客戶'
                LEFT JOIN orders o ON l.record_id = o.id AND l.table_name = 'orders'
                LEFT JOIN products p ON l.record_id = p.id AND l.table_name = 'products'
                WHERE {where_clause}
            """
            cursor.execute(count_query, params)
            total_count = cursor.fetchone()[0]

            # 獲取日誌數據
            query = f"""
                SELECT l.id, l.table_name, l.operation_type, l.record_id,
                       l.operation_detail, l.performed_by, l.user_type, l.created_at,
                       CASE
                           WHEN l.user_type = '管理員' THEN a.staff_no
                           WHEN l.user_type = '客戶' THEN c.company_name
                           ELSE '未知'
                       END as performer_name,
                       CASE
                           WHEN l.table_name = 'orders' THEN COALESCE(o.order_number, CAST(l.record_id AS TEXT))
                           WHEN l.table_name = 'products' THEN COALESCE(p.name, CAST(l.record_id AS TEXT))
                           WHEN l.table_name = 'customers' THEN COALESCE(c.company_name, CAST(l.record_id AS TEXT))
                           WHEN l.table_name = 'administrators' THEN COALESCE(a.staff_no, CAST(l.record_id AS TEXT))
                           ELSE CAST(l.record_id AS TEXT)
                       END as record_detail
                FROM logs l
                LEFT JOIN administrators a ON l.performed_by = a.id AND l.user_type = '管理員'
                LEFT JOIN customers c ON l.performed_by = c.id AND l.user_type = '客戶'
                LEFT JOIN orders o ON l.record_id = o.id AND l.table_name = 'orders'
                LEFT JOIN products p ON l.record_id = p.id AND l.table_name = 'products'
                WHERE {where_clause}
                ORDER BY l.created_at DESC
                LIMIT %s OFFSET %s
            """

            params.extend([limit, offset])
            cursor.execute(query, params)

            log_list = []
            for row in cursor.fetchall():
                log_dict = {
                    'id': row[0],
                    'table_name': row[1],
                    'operation_type': row[2],
                    'record_id': row[3],
                    'operation_detail': row[4],
                    'performed_by': row[5],
                    'user_type': row[6],
                    'created_at': row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] else None,
                    'performer_name': row[8],
                    'record_detail': row[9]
                }
                log_list.append(log_dict)

            return log_list, total_count
        except Exception as e:
            print(f"Error getting logs: {str(e)}")
            return [], 0 