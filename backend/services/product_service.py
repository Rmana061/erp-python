from typing import Dict, Any, List, Optional, Tuple

class ProductService:
    """產品服務類，處理產品相關的業務邏輯"""
    
    def __init__(self, db_connection):
        """初始化產品服務
        
        Args:
            db_connection: 數據庫連接對象
        """
        self.db_connection = db_connection
    
    def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        """获取指定产品信息"""
        try:
            cursor = self.db_connection.cursor()
            
            query = """
                SELECT 
                    id, name, description, image_url, dm_url, 
                    min_order_qty, max_order_qty, product_unit, 
                    shipping_time, special_date, status, created_at, updated_at
                FROM products
                WHERE id = %s
            """
            
            cursor.execute(query, (product_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
                
            # 列名
            columns = [desc[0] for desc in cursor.description]
            
            # 将结果转为字典
            product = dict(zip(columns, row))
            
            return product
            
        except Exception as e:
            print(f"获取产品信息错误: {str(e)}")
            return None
    
    def add_product(self, name, description, image_url='', dm_url='', 
                   min_order_qty=0, max_order_qty=0, product_unit='', 
                   shipping_time=0, special_date=False, status='active'):
        """添加新產品"""
        try:
            # 插入產品
            cursor = self.db_connection.cursor()
            
            insert_sql = """
                INSERT INTO products (
                    name, description, image_url, dm_url, 
                    min_order_qty, max_order_qty, product_unit, 
                    shipping_time, special_date, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            
            params = (
                name, description, image_url, dm_url, 
                min_order_qty, max_order_qty, product_unit, 
                shipping_time, special_date, status
            )
            
            print(f"SQL插入參數: {params}")
            cursor.execute(insert_sql, params)
            
            # 獲取產品ID (PostgreSQL方式)
            result = cursor.fetchone()
            product_id = result[0] if result else None
            print(f"SQL返回結果: {result}")
            
            # 提交事務
            self.db_connection.commit()
            
            # 提取產品ID
            if product_id:
                print(f"提取的產品ID: {product_id}")
                return product_id
            
            # 如果沒有ID，返回None
            return None
            
        except Exception as e:
            print(f"添加產品錯誤: {str(e)}")
            self.db_connection.rollback()
            raise e
    
    def update_product(self, product_id: int, product_data: Dict[str, Any]) -> bool:
        """更新产品信息"""
        try:
            cursor = self.db_connection.cursor()
            
            # 构建更新语句
            update_fields = []
            params = []
            
            # 添加需要更新的字段
            if 'name' in product_data:
                update_fields.append("name = %s")
                params.append(product_data['name'])
                
            if 'description' in product_data:
                update_fields.append("description = %s")
                params.append(product_data['description'])
                
            if 'image_url' in product_data:
                update_fields.append("image_url = %s")
                params.append(product_data['image_url'])
                
            if 'dm_url' in product_data:
                update_fields.append("dm_url = %s")
                params.append(product_data['dm_url'])
                
            if 'min_order_qty' in product_data:
                update_fields.append("min_order_qty = %s")
                params.append(product_data['min_order_qty'])
                
            if 'max_order_qty' in product_data:
                update_fields.append("max_order_qty = %s")
                params.append(product_data['max_order_qty'])
                
            if 'product_unit' in product_data:
                update_fields.append("product_unit = %s")
                params.append(product_data['product_unit'])
                
            if 'shipping_time' in product_data:
                update_fields.append("shipping_time = %s")
                params.append(product_data['shipping_time'])
                
            if 'special_date' in product_data:
                update_fields.append("special_date = %s")
                params.append(product_data['special_date'])
                
            if 'status' in product_data:
                update_fields.append("status = %s")
                params.append(product_data['status'])
            
            # 添加更新时间
            update_fields.append("updated_at = NOW()")
            
            # 没有字段需要更新时返回成功
            if not update_fields:
                return True
                
            # 构建最终SQL语句
            set_clause = ", ".join(update_fields)
            update_sql = f"UPDATE products SET {set_clause} WHERE id = %s"
            
            # 添加产品ID作为最后一个参数
            params.append(product_id)
            
            # 执行SQL
            cursor.execute(update_sql, params)
            
            # 检查更新是否成功
            self.db_connection.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            print(f"更新产品错误: {str(e)}")
            self.db_connection.rollback()
            raise e
    
    def delete_product(self, product_id: int) -> bool:
        """删除产品"""
        try:
            cursor = self.db_connection.cursor()
            
            # 执行删除SQL
            delete_sql = "DELETE FROM products WHERE id = %s"
            cursor.execute(delete_sql, (product_id,))
            
            # 检查删除是否成功
            self.db_connection.commit()
            return cursor.rowcount > 0
            
        except Exception as e:
            print(f"删除产品错误: {str(e)}")
            self.db_connection.rollback()
            raise e
    
    def get_product_list(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """獲取產品列表
        
        Args:
            limit: 每頁數量
            offset: 偏移量
            
        Returns:
            產品列表
        """
        try:
            cursor = self.db_connection.cursor()
            
            print(f"正在獲取產品列表，limit: {limit}, offset: {offset}")
            
            # 確保使用適合PostgreSQL的SQL
            query = """
                SELECT 
                    id, name, description, image_url, dm_url, 
                    min_order_qty, max_order_qty, product_unit, 
                    shipping_time, special_date, created_at, updated_at
                FROM products 
                WHERE status = 'active'
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            
            cursor.execute(query, (limit, offset))
            product_rows = cursor.fetchall()
            
            # 將結果轉換為字典列表
            columns = [col[0] for col in cursor.description]
            products = []
            
            # 詳細記錄每個產品
            for row in product_rows:
                product_dict = dict(zip(columns, row))
                products.append(product_dict)
                print(f"找到產品: ID={product_dict.get('id')}, 名稱={product_dict.get('name')}, 創建時間={product_dict.get('created_at')}")
            
            cursor.close()
            
            print(f"成功獲取 {len(products)} 個產品")
            return products
        except Exception as e:
            print(f"獲取產品列表錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            return [] 