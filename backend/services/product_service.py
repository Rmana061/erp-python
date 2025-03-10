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
                   shipping_time=0, special_date=False, status='active',
                   image_original_filename='', dm_original_filename=''):
        """添加新產品"""
        try:
            cursor = self.db_connection.cursor()
            
            # 插入新產品
            sql = """
                INSERT INTO products (
                    name, description, image_url, dm_url,
                    min_order_qty, max_order_qty, product_unit,
                    shipping_time, special_date, status, 
                    image_original_filename, dm_original_filename,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                )
            """
            
            params = (
                name, description, image_url, dm_url,
                min_order_qty, max_order_qty, product_unit,
                shipping_time, special_date, status,
                image_original_filename, dm_original_filename
            )
            
            cursor.execute(sql, params)
            self.db_connection.commit()
            
            # 返回新插入的產品ID
            return cursor.lastrowid
        except Exception as e:
            print(f"添加产品错误: {str(e)}")
            self.db_connection.rollback()
            return 0
    
    def update_product(self, product_id, data):
        """更新產品信息"""
        try:
            # 构建更新查询
            query = """
                UPDATE products
                SET name = %s, description = %s, image_url = %s, dm_url = %s,
                    min_order_qty = %s, max_order_qty = %s, product_unit = %s,
                    shipping_time = %s, special_date = %s, status = %s,
                    image_original_filename = %s, dm_original_filename = %s,
                    updated_at = NOW()
                WHERE id = %s
            """
            
            params = (
                data['name'], data['description'], data['image_url'], data['dm_url'],
                data['min_order_qty'], data['max_order_qty'], data['product_unit'],
                data['shipping_time'], data['special_date'], data['status'],
                data.get('image_original_filename'), data.get('dm_original_filename'),
                product_id
            )
            
            cursor = self.db_connection.cursor()
            cursor.execute(query, params)
            self.db_connection.commit()
            return True
        except Exception as e:
            print(f"更新产品失败: {str(e)}")
            self.db_connection.rollback()
            return False
    
    def delete_product(self, product_id: int, soft_delete: bool = True) -> bool:
        """删除或软删除产品
        
        Args:
            product_id: 产品ID
            soft_delete: 是否启用软删除，默认为True
            
        Returns:
            bool: 操作是否成功
        """
        try:
            cursor = self.db_connection.cursor()
            
            if soft_delete:
                # 执行软删除（更新状态）
                update_sql = "UPDATE products SET status = 'inactive' WHERE id = %s"
                cursor.execute(update_sql, (product_id,))
            else:
                # 执行硬删除
                delete_sql = "DELETE FROM products WHERE id = %s"
                cursor.execute(delete_sql, (product_id,))
            
            # 检查操作是否成功
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