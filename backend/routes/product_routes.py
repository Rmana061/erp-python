from flask import Blueprint, request, jsonify, send_from_directory
from backend.config.database import get_db_connection
from backend.utils.file_handlers import (
    create_product_folder, 
    allowed_image_file, 
    allowed_doc_file, 
    UPLOAD_FOLDER
)
from werkzeug.utils import secure_filename
import os

product_bp = Blueprint('product', __name__)

@product_bp.route('/products/list', methods=['POST'])
def get_products():
    try:
        data = request.json
        type = data.get('type', 'customer')
        customer_id = data.get('customer_id')

        with get_db_connection() as conn:
            cursor = conn.cursor()

            if type == 'admin':
                cursor.execute("""
                    SELECT id, name, description, image_url, dm_url, 
                           min_order_qty, max_order_qty, product_unit, 
                           shipping_time, special_date, created_at, updated_at 
                    FROM products
                    WHERE status = 'active'
                """)
            else:
                if not customer_id:
                    return jsonify({
                        "status": "error",
                        "message": "Missing customer_id"
                    }), 400

                # 先獲取客戶可見的產品列表
                cursor.execute("""
                    SELECT viewable_products
                    FROM customers
                    WHERE id = %s AND status = 'active'
                """, (customer_id,))
                
                result = cursor.fetchone()
                if not result or not result[0]:
                    return jsonify({
                        "status": "error",
                        "message": "No viewable products found for this customer"
                    }), 404

                product_ids = result[0].split(',')
                placeholders = ','.join(['%s'] * len(product_ids))
                
                cursor.execute(f"""
                    SELECT id, name, description, image_url, dm_url, 
                           min_order_qty, max_order_qty, product_unit, 
                           shipping_time, special_date, created_at, updated_at 
                    FROM products
                    WHERE status = 'active' AND id IN ({placeholders})
                """, tuple(product_ids))

            columns = [desc[0] for desc in cursor.description]
            products = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            cursor.close()
            
            return jsonify({
                "status": "success",
                "data": products
            })
    except Exception as e:
        print(f"Error in get_products: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@product_bp.route('/products/add', methods=['POST'])
def add_product():
    try:
        data = request.json
        
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            required_fields = ['name', 'description', 'min_order_qty', 'max_order_qty', 'product_unit']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'status': 'error',
                        'message': f'Missing required field: {field}'
                    }), 400
            
            cursor.execute("""
                INSERT INTO products (
                    name, description, image_url, dm_url,
                    min_order_qty, max_order_qty, product_unit,
                    shipping_time, special_date, status,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id
            """, (
                data.get('name'),
                data.get('description'),
                data.get('image_url'),
                data.get('dm_url'),
                data.get('min_order_qty'),
                data.get('max_order_qty'),
                data.get('product_unit'),
                data.get('shipping_time'),
                data.get('special_date', False),
                'active'
            ))
            
            new_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'message': 'Product added successfully',
                'id': new_id
            })
            
    except Exception as e:
        print(f"Error in add_product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/update/<int:product_id>', methods=['POST'])
def update_product(product_id):
    try:
        data = request.json
        
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
            if cursor.fetchone() is None:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
                
            required_fields = ['name', 'description', 'min_order_qty', 'max_order_qty', 'product_unit']
            for field in required_fields:
                if not data.get(field):
                    return jsonify({
                        'status': 'error',
                        'message': f'Missing required field: {field}'
                    }), 400
            
            cursor.execute("""
                UPDATE products 
                SET name = %s,
                    description = %s,
                    image_url = %s,
                    dm_url = %s,
                    min_order_qty = %s,
                    max_order_qty = %s,
                    product_unit = %s,
                    shipping_time = %s,
                    special_date = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                data.get('name'),
                data.get('description'),
                data.get('image_url'),
                data.get('dm_url'),
                data.get('min_order_qty'),
                data.get('max_order_qty'),
                data.get('product_unit'),
                data.get('shipping_time'),
                data.get('special_date', False),
                product_id
            ))
            
            conn.commit()
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'message': f'Product {product_id} updated successfully',
                'id': product_id
            })
            
    except Exception as e:
        print(f"Error in update_product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@product_bp.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE products 
                SET status = 'inactive', 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s
            """, (product_id,))
                
            if cursor.rowcount == 0:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
                
            conn.commit()
            cursor.close()
            
            return jsonify({
                'status': 'success',
                'message': f'Product {product_id} status updated to inactive'
            })
    except Exception as e:
        print(f"Error in delete_product: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
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