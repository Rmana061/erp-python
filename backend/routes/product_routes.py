from flask import Blueprint, request, jsonify, send_from_directory, current_app, abort, session
from backend.config.database import get_db_connection
from backend.utils.file_handlers import (
    create_product_folder, 
    allowed_image_file, 
    allowed_doc_file, 
    UPLOAD_FOLDER
)
from werkzeug.utils import secure_filename
import os
import uuid
from datetime import datetime
from backend.services.product_service import ProductService
from backend.services.log_service import LogService
from backend.services.log_service_registry import LogServiceRegistry
import json

product_bp = Blueprint('product', __name__)

@product_bp.route('/products/list', methods=['POST'])
def get_products():
    try:
        # 從session獲取管理員ID
        admin_id = session.get('admin_id')
        if not admin_id:
            data = request.get_json()
            if data and data.get('type') == 'admin':
                # 允許通過請求中的type=admin繼續
                pass
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Unauthorized access'
                }), 401
        
        print("正在獲取產品列表...")
        
        with get_db_connection() as conn:
            # 使用ProductService獲取產品列表
            product_service = ProductService(conn)
            products = product_service.get_product_list(limit=100, offset=0)
            
            print(f"API返回 {len(products)} 個產品")
            
            return jsonify({
                'status': 'success',
                'data': products
            })
    
    except Exception as e:
        print(f"獲取產品列表錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/add', methods=['POST'])
def add_product():
    """添加新產品"""
    try:
        # 獲取管理員ID
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 401
            
        # 顯示原始請求數據
        data = request.get_json()
        print(f"收到的原始請求數據: {data}")
        
        # 過濾出需要的數據
        filtered_data = {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'image_url': data.get('image_url', ''),
            'dm_url': data.get('dm_url', ''),
            'min_order_qty': data.get('min_order_qty', 0),
            'max_order_qty': data.get('max_order_qty', 0),
            'product_unit': data.get('product_unit', ''),
            'shipping_time': data.get('shipping_time', 0),
            'special_date': data.get('special_date', False)
        }
        print(f"過濾後的數據: {filtered_data}")
        
        with get_db_connection() as conn:
            try:
                # 添加產品
                print(f"准備添加產品，數據: {filtered_data}")
                product_service = ProductService(conn)
                product_id = product_service.add_product(
                    name=filtered_data['name'],
                    description=filtered_data['description'],
                    image_url=filtered_data['image_url'],
                    dm_url=filtered_data['dm_url'],
                    min_order_qty=filtered_data['min_order_qty'],
                    max_order_qty=filtered_data['max_order_qty'],
                    product_unit=filtered_data['product_unit'],
                    shipping_time=filtered_data['shipping_time'],
                    special_date=filtered_data['special_date']
                )
                print(f"產品添加結果ID: {product_id}")
                
                # 記錄操作日誌
                try:
                    # 僅傳遞必要的字段以避免序列化問題
                    log_data = {
                        'name': filtered_data['name'],
                        'description': filtered_data['description'],
                        'image_url': filtered_data['image_url'],
                        'dm_url': filtered_data['dm_url'],
                        'min_order_qty': filtered_data['min_order_qty'],
                        'max_order_qty': filtered_data['max_order_qty'],
                        'product_unit': filtered_data['product_unit'],
                        'shipping_time': filtered_data['shipping_time'],
                        'special_date': filtered_data['special_date']
                    }
                    
                    log_service = LogServiceRegistry.get_service(conn, 'products')
                    print("Received log operation request:")
                    print(f"Table: products")
                    print(f"Operation: 新增")
                    print(f"Record ID: {product_id}")
                    print(f"New data: {json.dumps(log_data)}")
                    print(f"Performed by: {admin_id}")
                    print(f"User type: 管理員")
                    
                    log_service.log_operation(
                        table_name='products',
                        operation_type='新增',
                        record_id=product_id,
                        old_data=None,
                        new_data=log_data,
                        performed_by=admin_id,
                        user_type='管理員'
                    )
                    print("產品新增日誌記錄成功")
                except Exception as e:
                    print(f"日誌記錄錯誤: {str(e)}")
                
                # 返回成功訊息
                return jsonify({
                    'status': 'success',
                    'message': '產品添加成功',
                    'product_id': product_id
                })
            except Exception as e:
                print(f"添加產品時發生錯誤: {str(e)}")
                conn.rollback()
                return jsonify({
                    'status': 'error',
                    'message': f'添加產品失敗: {str(e)}'
                }), 500
    except Exception as e:
        print(f"添加產品路由錯誤: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'添加產品時發生錯誤: {str(e)}'
        }), 500

@product_bp.route('/products/update/<int:product_id>', methods=['POST'])
def update_product(product_id):
    """更新產品信息"""
    try:
        # 獲取管理員ID
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 401
            
        data = request.get_json()
        print(f"更新產品ID: {product_id}, 數據: {data}")
        
        # 過濾出需要的數據
        filtered_data = {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'image_url': data.get('image_url', ''),
            'dm_url': data.get('dm_url', ''),
            'min_order_qty': data.get('min_order_qty', 0),
            'max_order_qty': data.get('max_order_qty', 0),
            'product_unit': data.get('product_unit', ''),
            'shipping_time': data.get('shipping_time', 0),
            'special_date': data.get('special_date', False),
            'status': data.get('status', 'active')
        }
        
        with get_db_connection() as conn:
            try:
                # 獲取更新前的產品數據（用於日誌記錄）
                product_service = ProductService(conn)
                old_product = product_service.get_product_by_id(product_id)
                
                if not old_product:
                    return jsonify({
                        'status': 'error',
                        'message': 'Product not found'
                    }), 404
                
                # 输出完整的旧数据以便调试
                print(f"更新前的原始数据: {old_product}")
                
                # 更新產品
                result = product_service.update_product(product_id, filtered_data)
                print(f"產品更新結果: {result}")
                
                if result:
                    # 記錄操作日誌
                    try:
                        log_service = LogServiceRegistry.get_service(conn, 'products')
                        print("Received log operation request:")
                        print(f"Table: products")
                        print(f"Operation: 修改")
                        print(f"Record ID: {product_id}")
                        print(f"Old data: {json.dumps(old_product, default=str)}")
                        print(f"New data: {json.dumps(filtered_data)}")
                        print(f"Performed by: {admin_id}")
                        print(f"User type: 管理員")
                        
                        log_service.log_operation(
                            table_name='products',
                            operation_type='修改',
                            record_id=product_id,
                            old_data=old_product,
                            new_data=filtered_data,
                            performed_by=admin_id,
                            user_type='管理員'
                        )
                        print("產品修改日誌記錄成功")
                    except Exception as e:
                        print(f"日誌記錄錯誤: {str(e)}")
                    
                    return jsonify({
                        'status': 'success',
                        'message': '產品更新成功'
                    })
                else:
                    return jsonify({
                        'status': 'error',
                        'message': '產品更新失敗'
                    }), 500
            except Exception as e:
                print(f"更新產品時發生錯誤: {str(e)}")
                conn.rollback()
                return jsonify({
                    'status': 'error',
                    'message': f'更新產品失敗: {str(e)}'
                }), 500
    except Exception as e:
        print(f"更新產品路由錯誤: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'更新產品時發生錯誤: {str(e)}'
        }), 500

@product_bp.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    """刪除產品"""
    try:
        # 獲取管理員ID
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 401
        
        print(f"刪除產品ID: {product_id}")
        
        # 獲取要刪除的產品數據（用於日誌記錄）
        with get_db_connection() as conn:
            product_service = ProductService(conn)
            product = product_service.get_product_by_id(product_id)
            
            if not product:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
            
            # 刪除產品
            result = product_service.delete_product(product_id)
            print(f"刪除產品結果: {result}")
            
            if result:
                # 記錄操作日誌
                try:
                    log_service = LogServiceRegistry.get_service(conn, 'products')
                    log_service.log_operation(
                        table_name='products',
                        operation_type='刪除',
                        record_id=product_id,
                        old_data=product,
                        new_data=None,
                        performed_by=admin_id,
                        user_type='管理員'
                    )
                    print("產品刪除日誌記錄成功")
                except Exception as e:
                    print(f"日誌記錄錯誤: {str(e)}")
                
                return jsonify({
                    'status': 'success',
                    'message': '產品刪除成功'
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': '產品刪除失敗'
                }), 500
    except Exception as e:
        print(f"刪除產品時發生錯誤: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'刪除產品失敗: {str(e)}'
        }), 500

@product_bp.route('/upload/image', methods=['POST'])
def upload_image():
    try:
        if 'file' not in request.files or 'productName' not in request.form:
            return jsonify({
                'status': 'error',
                'message': 'Missing file or product name'
            }), 400
            
        file = request.files['file']
        product_name = request.form['productName']
        
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': 'No selected file'
            }), 400
            
        if file and allowed_image_file(file.filename):
            file_ext = os.path.splitext(file.filename)[1]
            new_filename = secure_filename(product_name) + file_ext
            
            product_folder = create_product_folder(product_name)
            filepath = os.path.join(product_folder, new_filename)
            
            file.save(filepath)
            
            relative_path = os.path.join('uploads', secure_filename(product_name), new_filename)
            return jsonify({
                'status': 'success',
                'data': {
                    'file_path': f'/{relative_path.replace(os.sep, "/")}'
                }
            })
            
        return jsonify({
            'status': 'error',
            'message': 'File type not allowed'
        }), 400
    except Exception as e:
        print(f"Error in upload_image: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/upload/document', methods=['POST'])
def upload_document():
    try:
        if 'file' not in request.files or 'productName' not in request.form:
            return jsonify({
                'status': 'error',
                'message': 'Missing file or product name'
            }), 400
            
        file = request.files['file']
        product_name = request.form['productName']
        
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': 'No selected file'
            }), 400
            
        if file and allowed_doc_file(file.filename):
            file_ext = os.path.splitext(file.filename)[1]
            new_filename = secure_filename(product_name) + file_ext
            
            product_folder = create_product_folder(product_name)
            filepath = os.path.join(product_folder, new_filename)
            
            file.save(filepath)
            
            relative_path = os.path.join('uploads', secure_filename(product_name), new_filename)
            return jsonify({
                'status': 'success',
                'data': {
                    'file_path': f'/{relative_path.replace(os.sep, "/")}'
                }
            })
            
        return jsonify({
            'status': 'error',
            'message': 'File type not allowed'
        }), 400
            
    except Exception as e:
        print(f"Error in upload_document: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/uploads/<path:filename>', methods=['POST'])
def uploaded_file(filename):
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        print(f"Error in uploaded_file: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/viewable', methods=['POST'])
def get_viewable_products():
    try:
        data = request.json
        product_ids = data.get('ids')
        if not product_ids:
            return jsonify({'error': 'No product IDs provided'}), 400

        # Split the comma-separated string into a list if it's a string
        id_list = product_ids.split(',') if isinstance(product_ids, str) else product_ids
        # Create placeholders for SQL query
        placeholders = ','.join(['%s'] * len(id_list))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT id, name, description, min_order_qty, max_order_qty, 
                       product_unit, shipping_time, special_date, status
                FROM products 
                WHERE id IN ({placeholders})
                AND status = 'active'
            """, tuple(id_list))

            columns = [desc[0] for desc in cursor.description]
            products = [dict(zip(columns, row)) for row in cursor.fetchall()]

            cursor.close()
            
            return jsonify({
                'status': 'success',
                'data': products
            })

    except Exception as e:
        print(f"Error in get_viewable_products: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/locked-dates', methods=['POST'])
def get_locked_dates():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, locked_date, created_at
                FROM locked_dates
                ORDER BY locked_date ASC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            dates = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": dates
            })
            
    except Exception as e:
        print(f"Error in get_locked_dates: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@product_bp.route('/products/lock-date', methods=['POST'])
def lock_date():
    try:
        data = request.json
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403
            
        if 'date' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing date parameter'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 检查日期是否已经被锁定
            cursor.execute("""
                SELECT id FROM locked_dates
                WHERE locked_date = %s
            """, (data['date'],))
            
            if cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': '该日期已被锁定'
                }), 400
            
            # 插入新的锁定日期
            cursor.execute("""
                INSERT INTO locked_dates (locked_date, created_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                RETURNING id
            """, (data['date'],))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'message': '日期锁定成功',
                'id': new_id
            })
            
    except Exception as e:
        print(f"Error in lock_date: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/unlock-date', methods=['POST'])
def unlock_date():
    try:
        data = request.json
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403
            
        if 'date_id' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing date_id parameter'
            }), 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 删除锁定日期
            cursor.execute("""
                DELETE FROM locked_dates
                WHERE id = %s
                RETURNING id
            """, (data['date_id'],))
            
            if not cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': '找不到该锁定日期'
                }), 404
            
            conn.commit()
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'message': '日期解鎖成功'
            })
            
    except Exception as e:
        print(f"Error in unlock_date: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/<int:product_id>/detail', methods=['POST'])
def get_product_detail(product_id):
    try:
        data = request.json
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, description, image_url, dm_url, 
                       min_order_qty, max_order_qty, product_unit, 
                       shipping_time, special_date, created_at, updated_at 
                FROM products
                WHERE id = %s AND status = 'active'
            """, (product_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    'status': 'error',
                    'message': '找不到該產品'
                }), 404

            columns = [desc[0] for desc in cursor.description]
            product_data = dict(zip(columns, result))
            
            # 格式化日期
            if product_data.get('created_at'):
                product_data['created_at'] = product_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if product_data.get('updated_at'):
                product_data['updated_at'] = product_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')

            return jsonify({
                'status': 'success',
                'data': product_data
            })
            
    except Exception as e:
        print(f"Error in get_product_detail: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500 