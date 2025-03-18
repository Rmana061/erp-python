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
            
            # 檢查是否有變更
            if not operation_detail:
                print(f"No changes detected, skipping log entry")
                return False
                
            # 檢查是否是無變更的消息
            if isinstance(operation_detail, dict):
                message = operation_detail.get('message', '')
                if message == '無變更' or operation_detail.get('operation_type') is None:
                    print(f"No significant changes detected, skipping log entry")
                    return False
            
            # 如果operation_detail中沒有operation_type，使用傳入的operation_type
            if operation_detail and 'operation_type' not in operation_detail:
                operation_detail['operation_type'] = operation_type
            
            # 插入日誌記錄
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
                offset: int = 0,
                record_only_search: bool = False) -> tuple:
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
                # 基本的操作對象搜索條件
                base_condition = """
                    CASE
                        WHEN l.table_name = 'orders' THEN COALESCE(o.order_number, CAST(l.record_id AS TEXT))
                        WHEN l.table_name = 'products' AND ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL THEN 
                            CASE
                                WHEN (l.operation_detail)::jsonb->>'message' IS NOT NULL AND 
                                     (l.operation_detail)::jsonb->'message'->>'locked_date' IS NOT NULL AND
                                     (l.operation_detail)::jsonb->'message'->'locked_date'->>'date' IS NOT NULL
                                THEN (l.operation_detail)::jsonb->'message'->'locked_date'->>'date'
                                ELSE CAST(l.record_id AS TEXT)
                            END
                        WHEN l.table_name = 'products' THEN COALESCE(p.name, CAST(l.record_id AS TEXT))
                        WHEN l.table_name = 'customers' THEN COALESCE(c.company_name, CAST(l.record_id AS TEXT))
                        WHEN l.table_name = 'administrators' THEN COALESCE(a.staff_no, CAST(l.record_id AS TEXT))
                        ELSE CAST(l.record_id AS TEXT)
                    END
                """
                
                if record_only_search:
                    # 嚴格模式：只搜索操作對象
                    record_search_condition = f"({base_condition} ILIKE %s"
                else:
                    # 寬鬆模式：可以搜索操作對象和操作詳情
                    record_search_condition = f"({base_condition} ILIKE %s OR (l.operation_detail)::text ILIKE %s"
                    params.append(f'%{record_detail}%')  # 添加一個額外的參數用於操作詳情搜索
                
                # 添加參數
                like_pattern = f'%{record_detail}%'
                params.append(like_pattern)
                
                # 優化日期搜索 - 判斷是否為日期格式
                if record_detail.replace('-', '').isdigit() and '-' in record_detail:
                    date_parts = record_detail.split('-')
                    # 如果是日期部分 (例如 MM-DD)
                    if len(date_parts) == 2 and len(date_parts[0]) <= 2 and len(date_parts[1]) <= 2:
                        # 添加針對鎖定日期的特殊搜索條件
                        if record_only_search:
                            # 嚴格匹配日期格式，只搜索操作對象
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                (
                                    SUBSTRING(((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') FROM 6 FOR 5) = %s
                                )
                            )"""
                            # 严格匹配 MM-DD 部分
                            params.append(f'{date_parts[0]}-{date_parts[1]}')
                        else:
                            # 非嚴格模式，可以搜索operation_detail
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                (
                                    ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') LIKE %s OR
                                    ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') LIKE %s
                                )
                            )"""
                            params.append(f'%{date_parts[0]}-{date_parts[1]}%')  # 任何年份-指定月日
                            params.append(f'%{date_parts[0]}-{date_parts[1]}')    # 结尾是月日格式
                            
                            # 添加額外的日期搜索條件（針對一般operation_detail）
                            record_search_condition += " OR CAST((l.operation_detail)::text AS TEXT) LIKE %s"
                            params.append(f'%{date_parts[0]}-{date_parts[1]}%')  # 支持任何包含MM-DD的文本
                    # 如果是年份-月份 (例如 YYYY-MM)
                    elif len(date_parts) == 2 and len(date_parts[0]) == 4:
                        if record_only_search:
                            # 嚴格匹配日期格式，只搜索操作對象
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') LIKE %s
                            )"""
                            params.append(f'{date_parts[0]}-{date_parts[1]}-')  # 年份-月份开头
                        else:
                            # 非嚴格模式，可以搜索operation_detail
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') LIKE %s
                            )"""
                            params.append(f'{date_parts[0]}-{date_parts[1]}%')  # 年份-月份开头
                            
                            record_search_condition += " OR CAST((l.operation_detail)::text AS TEXT) LIKE %s"
                            params.append(f'%{date_parts[0]}-{date_parts[1]}%')
                    # 如果是完整日期 (例如 YYYY-MM-DD)
                    elif len(date_parts) == 3:
                        if record_only_search:
                            # 嚴格匹配日期格式，只搜索操作對象
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') = %s
                            )"""
                            params.append(f'{date_parts[0]}-{date_parts[1]}-{date_parts[2]}')  # 完整日期精确匹配
                        else:
                            # 非嚴格模式，可以搜索operation_detail
                            record_search_condition += """ OR (
                                ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL AND
                                ((l.operation_detail)::jsonb->'message'->'locked_date'->>'date') = %s
                            )"""
                            params.append(f'{date_parts[0]}-{date_parts[1]}-{date_parts[2]}')  # 完整日期精确匹配
                            
                            record_search_condition += " OR CAST((l.operation_detail)::text AS TEXT) LIKE %s"
                            params.append(f'%{record_detail}%')
                
                # 如果不是僅搜索操作對象，也搜索operation_detail - 已在上面處理，這裡不需要重複
                # 添加結束括號
                record_search_condition += ")"
                conditions.append(record_search_condition)

            # 構建 WHERE 子句
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            print(f"過濾條件: table_name={table_name}, operation_type={operation_type}, start_date={start_date}, end_date={end_date}, user_type={user_type}, performed_by={performed_by}, record_detail={record_detail}, record_only_search={record_only_search}")
            print(f"WHERE 子句: {where_clause}")
            print(f"參數: {params}")

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
            
            try:
                print(f"執行計數查詢: {count_query}")
                print(f"參數: {params}")
                cursor.execute(count_query, params)
                result = cursor.fetchone()
                print(f"計數查詢結果: {result}")
                total_count = result[0] if result else 0
                print(f"計算得到總記錄數: {total_count}")
            except Exception as count_error:
                print(f"計算總記錄數時出錯: {str(count_error)}")
                total_count = 0
                # 不中斷執行，繼續嘗試獲取記錄

            # 獲取日誌數據
            query = f"""
                SELECT 
                    l.id, 
                    l.table_name, 
                    l.operation_type, 
                    l.record_id,
                    l.operation_detail, 
                    l.performed_by, 
                    l.user_type, 
                    l.created_at,
                    CASE
                        WHEN l.user_type = '管理員' THEN a.staff_no
                        WHEN l.user_type = '客戶' THEN c.company_name
                        ELSE '未知'
                    END as performer_name,
                    CASE
                        WHEN l.table_name = 'orders' THEN COALESCE(o.order_number, CAST(l.record_id AS TEXT))
                        WHEN l.table_name = 'products' AND ((l.operation_detail)::jsonb->'message'->>'locked_date') IS NOT NULL THEN 
                            CASE
                                WHEN (l.operation_detail)::jsonb->>'message' IS NOT NULL AND 
                                     (l.operation_detail)::jsonb->'message'->>'locked_date' IS NOT NULL AND
                                     (l.operation_detail)::jsonb->'message'->'locked_date'->>'date' IS NOT NULL
                                THEN (l.operation_detail)::jsonb->'message'->'locked_date'->>'date'
                                ELSE CAST(l.record_id AS TEXT)
                            END
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

            params_copy = params.copy()  # 複製參數列表，避免影響原始參數
            params_copy.extend([limit, offset])
            
            try:
                print(f"執行記錄查詢: {query}")
                print(f"參數: {params_copy}")
                cursor.execute(query, params_copy)
                rows = cursor.fetchall()
                print(f"查詢到 {len(rows)} 條記錄")
                
                log_list = []
                for row in rows:
                    # 保護性地訪問每個欄位，防止索引越界
                    if len(row) >= 10:
                        log_dict = {
                            'id': row[0] if len(row) > 0 else None,
                            'table_name': row[1] if len(row) > 1 else None,
                            'operation_type': row[2] if len(row) > 2 else None,
                            'record_id': row[3] if len(row) > 3 else None,
                            'operation_detail': row[4] if len(row) > 4 else None,
                            'performed_by': row[5] if len(row) > 5 else None,
                            'user_type': row[6] if len(row) > 6 else None,
                            'created_at': row[7].strftime('%Y-%m-%d %H:%M:%S') if row[7] and len(row) > 7 else None,
                            'performer_name': row[8] if len(row) > 8 else '未知',
                            'record_detail': row[9] if len(row) > 9 else None
                        }
                        log_list.append(log_dict)
                    else:
                        print(f"警告: 跳過不完整的日誌記錄，只有 {len(row)} 個欄位: {row}")
                
                # 如果沒有記錄，返回空列表
                if not log_list:
                    print("沒有找到符合條件的日誌記錄")
                    
                return log_list, total_count
            except Exception as query_error:
                print(f"執行日誌查詢時出錯: {str(query_error)}")
                return [], total_count
                
        except Exception as e:
            print(f"Error getting logs: {str(e)}")
            print(f"錯誤堆疊: ", e.__traceback__)
            return [], 0 