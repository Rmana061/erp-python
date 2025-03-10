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
import base64
from datetime import datetime
from backend.services.product_service import ProductService
from backend.services.log_service import LogService
from backend.services.log_service_registry import LogServiceRegistry
import json
import time
import shutil
import urllib.parse

product_bp = Blueprint('product', __name__)

# 上传文件夹配置
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'uploads')

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def create_dual_filename(original_filename):
    """创建双轨文件名，格式为：uuid___base64编码的原始文件名.扩展名"""
    file_name, file_ext = os.path.splitext(original_filename)
    # 对原始文件名进行Base64编码，避免特殊字符问题
    encoded_original = base64.urlsafe_b64encode(file_name.encode()).decode()
    safe_part = f"{uuid.uuid4()}"
    return f"{safe_part}___{encoded_original}{file_ext}"

def extract_original_filename(dual_filename):
    """从双轨文件名中提取原始文件名"""
    try:
        # 分离文件名和扩展名
        file_name, file_ext = os.path.splitext(dual_filename)
        # 分离UUID和编码部分
        parts = file_name.split('___')
        if len(parts) > 1:
            # 解码原始文件名
            original_name = base64.urlsafe_b64decode(parts[1].encode()).decode()
            return f"{original_name}{file_ext}"
        return dual_filename
    except:
        return dual_filename  # 如果解析失败，返回原文件名

def remove_product_folder(product_folder):
    """删除产品相关的上传文件夹
    
    Args:
        product_folder: 产品名称或文件夹名称
    
    Returns:
        bool: 是否成功删除
    """
    try:
        # 安全起见，检查文件夹名称合法性
        folder_name = secure_filename(product_folder)
        if not folder_name:
            print("产品文件夹名称无效")
            return False
            
        # 检查该名称的文件夹是否存在
        folder_path = os.path.join(UPLOAD_FOLDER, folder_name)
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            # 删除文件夹及其内容
            shutil.rmtree(folder_path)
            print(f"已删除产品文件夹: {folder_path}")
            return True
        else:
            print(f"产品文件夹不存在: {folder_path}")
            return False
    except Exception as e:
        print(f"删除产品文件夹时出错: {str(e)}")
        return False

@product_bp.route('/products/list', methods=['POST'])
def get_products():
    try:
        # 獲取請求數據
        data = request.get_json()
        request_type = data.get('type') if data else None
        
        # 檢查請求類型
        if request_type == 'admin':
            # 從session獲取管理員ID或請求頭獲取
            admin_id = session.get('admin_id')
            if not admin_id:
                return jsonify({
                    'status': 'error',
                    'message': 'Unauthorized access'
                }), 401
            
            print("管理員請求產品列表")
            
        elif request_type == 'customer':
            # 客戶請求產品，檢查客戶身份
            customer_id = data.get('customer_id')
            company_name = data.get('company_name')
            
            # 從頭部獲取客戶信息（兼容ngrok環境）
            header_customer_id = request.headers.get('X-Customer-ID')
            header_company_name = request.headers.get('X-Company-Name')
            
            # 優先使用頭部信息，其次使用請求體信息
            customer_id = header_customer_id or customer_id
            company_name = header_company_name or company_name
            
            # 從session獲取客戶訊息
            session_customer_id = session.get('customer_id')
            session_company_name = session.get('company_name')
            
            print("當前會話狀態:", {
                'customerId': customer_id,
                'companyName': company_name,
                'sessionCustomerId': session_customer_id,
                'sessionCompanyName': session_company_name,
                'isLoggedIn': True if session_customer_id else False
            })
            
            # 驗證客戶身份 - 使用session或提供的ID和公司名
            if not ((session_customer_id and session_customer_id == int(customer_id)) or
                   (customer_id and company_name)):
                return jsonify({
                    'status': 'error', 
                    'message': 'Unauthorized access'
                }), 401
                
            print(f"獲取客戶 {customer_id}（{company_name}）的產品列表")
            
        else:
            return jsonify({
                'status': 'error',
                'message': 'Invalid request type'
            }), 400
        
        print("正在獲取產品列表...")
        
        with get_db_connection() as conn:
            # 使用ProductService獲取產品列表
            product_service = ProductService(conn)
            
            # 使用通用的get_product_list方法获取产品
            # 目前ProductService中没有专门针对客户的方法，所以使用通用方法
            products = product_service.get_product_list(limit=100, offset=0)
            
            # 处理每个产品的文件URL，提取原始文件名
            for product in products:
                if product.get('image_url'):
                    image_path = product['image_url']
                    image_filename = os.path.basename(image_path)
                    try:
                        # 尝试提取原始文件名
                        original_image_filename = extract_original_filename(image_filename)
                        # 添加原始文件名字段
                        if original_image_filename != image_filename:
                            product['original_image_filename'] = original_image_filename
                    except Exception as e:
                        print(f"提取图片原始文件名出错: {str(e)}")
                
                if product.get('dm_url'):
                    dm_path = product['dm_url']
                    dm_filename = os.path.basename(dm_path)
                    try:
                        # 尝试提取原始文件名
                        original_dm_filename = extract_original_filename(dm_filename)
                        # 添加原始文件名字段
                        if original_dm_filename != dm_filename:
                            product['original_dm_filename'] = original_dm_filename
                    except Exception as e:
                        print(f"提取文档原始文件名出错: {str(e)}")
            
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
            'special_date': data.get('special_date', False),
            # 添加原始文件名字段
            'image_original_filename': data.get('image_original_filename', ''),
            'dm_original_filename': data.get('dm_original_filename', '')
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
                    special_date=filtered_data['special_date'],
                    # 添加原始文件名参数
                    image_original_filename=filtered_data['image_original_filename'],
                    dm_original_filename=filtered_data['dm_original_filename']
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
                        'special_date': filtered_data['special_date'],
                        # 添加原始文件名到日志数据中
                        'image_original_filename': filtered_data['image_original_filename'],
                        'dm_original_filename': filtered_data['dm_original_filename']
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
        
        # 獲取更新前的產品數據
        with get_db_connection() as conn:
            product_service = ProductService(conn)
            old_product = product_service.get_product_by_id(product_id)
            
            if not old_product:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
            
            # 处理文件URL，提取原始文件名
            if old_product.get('image_url'):
                image_path = old_product['image_url']
                image_filename = os.path.basename(image_path)
                try:
                    # 尝试提取原始文件名
                    original_image_filename = extract_original_filename(image_filename)
                    # 添加原始文件名字段
                    if original_image_filename != image_filename:
                        old_product['original_image_filename'] = original_image_filename
                        print(f"图片文件名: {image_filename} -> 原始文件名: {original_image_filename}")
                except Exception as e:
                    print(f"提取图片原始文件名出错: {str(e)}")
            
            if old_product.get('dm_url'):
                dm_path = old_product['dm_url']
                dm_filename = os.path.basename(dm_path)
                try:
                    # 尝试提取原始文件名
                    original_dm_filename = extract_original_filename(dm_filename)
                    # 添加原始文件名字段
                    if original_dm_filename != dm_filename:
                        old_product['original_dm_filename'] = original_dm_filename
                        print(f"文档文件名: {dm_filename} -> 原始文件名: {original_dm_filename}")
                except Exception as e:
                    print(f"提取文档原始文件名出错: {str(e)}")
            
            # 輸出完整的舊數據以便調試
            print(f"更新前的原始数据: {old_product}")
            
            # 保留原始文件路徑，除非明確要求更換
            # 檢查是否有新的圖片上傳
            if data.get('image_url') and data.get('image_url') != old_product['image_url'] and '/uploads/' in data.get('image_url', ''):
                # 保持現有圖片URL
                print(f"檢測到新的圖片URL: {data.get('image_url')}")
                # 檢查URL格式是否異常（比如只有副檔名沒有文件名的情況）
                image_path = data.get('image_url', '')
                if image_path.endswith('/png') or image_path.endswith('/jpg') or image_path.endswith('/jpeg') or image_path.endswith('/gif') or image_path.endswith('/webp'):
                    print(f"檢測到異常的圖片URL格式，使用原URL: {old_product['image_url']}")
                    data['image_url'] = old_product['image_url']
                
            # 檢查是否有新的DM上傳
            if data.get('dm_url') and data.get('dm_url') != old_product['dm_url'] and '/uploads/' in data.get('dm_url', ''):
                # 保持現有DM URL
                print(f"檢測到新的DM URL: {data.get('dm_url')}")
                # 檢查URL格式是否異常
                dm_path = data.get('dm_url', '')
                if dm_path.endswith('/pdf') or dm_path.endswith('/doc') or dm_path.endswith('/docx') or dm_path.endswith('/xls') or dm_path.endswith('/xlsx') or dm_path.endswith('/ppt') or dm_path.endswith('/pptx'):
                    print(f"檢測到異常的DM URL格式，使用原URL: {old_product['dm_url']}")
                    data['dm_url'] = old_product['dm_url']
            
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
                'status': data.get('status', 'active'),
            }
            
            # 处理原始文件名：只在有新文件时更新原始文件名字段
            # 检查图片URL是否发生了变化
            if data.get('image_url') != old_product.get('image_url'):
                print(f"图片URL发生变化，使用新的原始文件名: {data.get('image_original_filename', '')}")
                filtered_data['image_original_filename'] = data.get('image_original_filename', '')
            else:
                print(f"图片URL未变化，保留原始文件名: {old_product.get('original_image_filename', '')}")
                filtered_data['image_original_filename'] = old_product.get('original_image_filename', '')
            
            # 检查文档URL是否发生了变化
            if data.get('dm_url') != old_product.get('dm_url'):
                print(f"文档URL发生变化，使用新的原始文件名: {data.get('dm_original_filename', '')}")
                filtered_data['dm_original_filename'] = data.get('dm_original_filename', '')
            else:
                print(f"文档URL未变化，保留原始文件名: {old_product.get('original_dm_filename', '')}")
                filtered_data['dm_original_filename'] = old_product.get('original_dm_filename', '')
            
            # 打印最终要更新的数据
            print(f"最终更新数据: {filtered_data}")
            
            try:
                # 更新產品
                result = product_service.update_product(product_id, filtered_data)
                print(f"產品更新結果: {result}")
                
                if result:
                    # 記錄操作日誌
                    try:
                        log_service = LogServiceRegistry.get_service(conn, 'products')
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
                        
                    # 獲取最新產品數據返回
                    updated_product = product_service.get_product_by_id(product_id)
                    
                    if updated_product:
                        return jsonify({
                            'status': 'success',
                            'message': '產品更新成功',
                            'data': updated_product
                        })
                    else:
                        return jsonify({
                            'status': 'error',
                            'message': '無法獲取更新後的產品數據'
                        }), 500
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
        # 獲取請求數據
        data = request.json or {}
        soft_delete = data.get('soft_delete', True)  # 預設使用軟刪除
        product_folder = data.get('product_folder', '')  # 產品文件夾名稱
        
        # 獲取管理員ID
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 401
        
        print(f"刪除產品ID: {product_id}, 軟刪除: {soft_delete}")
        
        # 獲取要刪除的產品數據（用於日誌記錄）
        with get_db_connection() as conn:
            product_service = ProductService(conn)
            product = product_service.get_product_by_id(product_id)
            
            if not product:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
            
            # 嘗試刪除uploads文件夾（如果有提供產品文件夾名稱）
            if product_folder:
                delete_folder_result = remove_product_folder(product_folder)
                print(f"刪除產品文件夾結果: {delete_folder_result}")
            
            # 刪除產品（軟刪除或硬刪除）
            result = product_service.delete_product(product_id, soft_delete=soft_delete)
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
                        new_data={'status': 'inactive'} if soft_delete else None,  # 軟刪除時記錄新狀態
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
            # 保存原始文件名（这将用于数据库存储）
            original_filename = file.filename
            
            # 创建安全文件名用于存储
            safe_filename = create_dual_filename(original_filename)
            
            product_folder = create_product_folder(product_name)
            filepath = os.path.join(product_folder, safe_filename)
            
            # 删除文件夹中所有现有的图片文件
            image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
            for existing_file in os.listdir(product_folder):
                file_ext = os.path.splitext(existing_file)[1].lower()
                if file_ext in image_extensions:
                    try:
                        os.remove(os.path.join(product_folder, existing_file))
                        print(f"已刪除舊圖片文件: {existing_file}")
                    except Exception as e:
                        print(f"刪除舊圖片時出錯: {str(e)}")
            
            # 保存新上传的文件
            file.save(filepath)
            
            # 确保返回的路径包含安全文件名（用于存储）
            relative_path = os.path.join('uploads', secure_filename(product_name), safe_filename)
            
            print(f"图片上传成功，完整路径: {relative_path}，原始文件名: {original_filename}")
            return jsonify({
                'status': 'success',
                'data': {
                    'file_path': f'/{relative_path.replace(os.sep, "/")}',
                    'original_filename': original_filename  # 返回原始文件名
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
            # 获取原始文件名
            original_filename = file.filename
            
            # 创建双轨文件名（安全存储同时保留原始信息）
            safe_filename = create_dual_filename(original_filename)
            
            product_folder = create_product_folder(product_name)
            filepath = os.path.join(product_folder, safe_filename)
            
            # 删除文件夹中所有现有的文档文件
            doc_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
            for existing_file in os.listdir(product_folder):
                file_ext = os.path.splitext(existing_file)[1].lower()
                if file_ext in doc_extensions:
                    try:
                        os.remove(os.path.join(product_folder, existing_file))
                        print(f"已删除旧文档文件: {existing_file}")
                    except Exception as e:
                        print(f"删除旧文档时出错: {str(e)}")
            
            # 保存新上传的文件
            file.save(filepath)
            
            # 确保返回的路径包含完整的文件名
            relative_path = os.path.join('uploads', secure_filename(product_name), safe_filename)
            print(f"文档上传成功，完整路径: {relative_path}，原始文件名: {original_filename}")
            return jsonify({
                'status': 'success',
                'data': {
                    'file_path': f'/{relative_path.replace(os.sep, "/")}',
                    'original_filename': original_filename
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

@product_bp.route('/file/<path:filename>')
def serve_product_file(filename):
    """处理产品相关文件的访问，支持显示原始文件名"""
    try:
        # 分离目录和文件名
        directory = os.path.dirname(filename)
        basename = os.path.basename(filename)
        
        # 尝试从数据库中获取原始文件名
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 尝试查找匹配的图片
            cursor.execute("SELECT image_original_filename FROM products WHERE image_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(
                    os.path.join(UPLOAD_FOLDER, directory) if directory else UPLOAD_FOLDER,
                    basename
                )
                response.headers["Content-Disposition"] = f"inline; filename=\"{original_filename}\""
                print(f"从数据库获取图片原始文件名: {original_filename}")
                return response
                
            # 尝试查找匹配的文档
            cursor.execute("SELECT dm_original_filename FROM products WHERE dm_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(
                    os.path.join(UPLOAD_FOLDER, directory) if directory else UPLOAD_FOLDER,
                    basename
                )
                response.headers["Content-Disposition"] = f"inline; filename=\"{original_filename}\""
                print(f"从数据库获取文档原始文件名: {original_filename}")
                return response
                
        # 如果数据库中没有找到，尝试从文件名中提取
        original_filename = extract_original_filename(basename)
        
        if original_filename and original_filename != basename:
            response = send_from_directory(
                os.path.join(UPLOAD_FOLDER, directory) if directory else UPLOAD_FOLDER,
                basename
            )
            response.headers["Content-Disposition"] = f"inline; filename=\"{original_filename}\""
            print(f"从文件名提取原始文件名: {original_filename}")
            return response
    except Exception as e:
        print(f"处理文件访问出错: {str(e)}")
    
    # 默认返回
    return send_from_directory(
        os.path.join(UPLOAD_FOLDER, directory) if directory else UPLOAD_FOLDER,
        basename
    )

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
    """获取产品详情"""
    try:
        # 获取管理员ID
        admin_id = session.get('admin_id')
        if not admin_id:
            data = request.get_json()
            if data and data.get('type') == 'admin':
                # 允许通过请求中的type=admin继续
                pass
            else:
                return jsonify({
                    'status': 'error',
                    'message': 'Unauthorized access'
                }), 401
        
        with get_db_connection() as conn:
            product_service = ProductService(conn)
            product = product_service.get_product_by_id(product_id)
            
            if not product:
                return jsonify({
                    'status': 'error',
                    'message': 'Product not found'
                }), 404
            
            # 处理文件URL，提取原始文件名
            if product.get('image_url'):
                image_path = product['image_url']
                image_filename = os.path.basename(image_path)
                try:
                    # 尝试提取原始文件名
                    original_image_filename = extract_original_filename(image_filename)
                    # 替换路径中的文件名部分
                    if original_image_filename != image_filename:
                        product['original_image_filename'] = original_image_filename
                        print(f"图片文件名: {image_filename} -> 原始文件名: {original_image_filename}")
                except Exception as e:
                    print(f"提取图片原始文件名出错: {str(e)}")
            
            if product.get('dm_url'):
                dm_path = product['dm_url']
                dm_filename = os.path.basename(dm_path)
                try:
                    # 尝试提取原始文件名
                    original_dm_filename = extract_original_filename(dm_filename)
                    # 替换路径中的文件名部分
                    if original_dm_filename != dm_filename:
                        product['original_dm_filename'] = original_dm_filename
                        print(f"文档文件名: {dm_filename} -> 原始文件名: {original_dm_filename}")
                except Exception as e:
                    print(f"提取文档原始文件名出错: {str(e)}")
            
            return jsonify({
                'status': 'success',
                'data': product
            })
    except Exception as e:
        print(f"获取产品详情错误: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500 