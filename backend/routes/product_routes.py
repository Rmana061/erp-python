from flask import Blueprint, request, jsonify, send_from_directory, current_app, abort, session, make_response, redirect
from backend.config.database import get_db_connection
from backend.utils.file_handlers import (
    create_product_folder, 
    allowed_image_file, 
    allowed_doc_file, 
    UPLOAD_FOLDER,
    save_file,
    delete_file,
    get_product_files,
    USE_AZURE_STORAGE
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
from backend.utils.scheduler import run_clean_task_manually

product_bp = Blueprint('product', __name__)

# 上传文件夹配置
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'uploads')

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def create_dual_filename(original_filename):
    """创建双轨文件名，格式为：uuid___base64编码的原始文件名.扩展名"""
    file_name, file_ext = os.path.splitext(original_filename)
    # 對原始文件名進行Base64編碼，無論是英文還是中文，確保所有檔案名都被加密
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
            
            # 處理每個產品的文件URL，確保包含原始文件名
            cursor = conn.cursor()
            for product in products:
                if product.get('id'):
                    # 直接從資料庫中獲取原始文件名
                    cursor.execute("""
                        SELECT image_original_filename, dm_original_filename 
                        FROM products 
                        WHERE id = %s
                    """, (product['id'],))
                    
                    result = cursor.fetchone()
                    if result:
                        if result[0]:  # 圖片原始文件名
                            product['original_image_filename'] = result[0]
                            product['image_original_filename'] = result[0]
                        
                        if result[1]:  # 文檔原始文件名
                            product['original_dm_filename'] = result[1]
                            product['dm_original_filename'] = result[1]
                
                # 如果數據庫中沒有原始文件名，嘗試從文件名中提取
                if product.get('image_url') and not product.get('original_image_filename'):
                    image_path = product['image_url']
                    image_filename = os.path.basename(image_path)
                    try:
                        # 尝试提取原始文件名
                        original_image_filename = extract_original_filename(image_filename)
                        # 添加原始文件名字段
                        if original_image_filename != image_filename:
                            product['original_image_filename'] = original_image_filename
                            product['image_original_filename'] = original_image_filename
                    except Exception as e:
                        print(f"提取图片原始文件名出错: {str(e)}")
                
                if product.get('dm_url') and not product.get('original_dm_filename'):
                    dm_path = product['dm_url']
                    dm_filename = os.path.basename(dm_path)
                    try:
                        # 尝试提取原始文件名
                        original_dm_filename = extract_original_filename(dm_filename)
                        # 添加原始文件名字段
                        if original_dm_filename != dm_filename:
                            product['original_dm_filename'] = original_dm_filename
                            product['dm_original_filename'] = original_dm_filename
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
            
            # 處理文件URL，確保包含原始文件名
            if old_product.get('image_url'):
                image_path = old_product['image_url']
                image_filename = os.path.basename(image_path)
                try:
                    # 尝试提取原始文件名
                    original_image_filename = extract_original_filename(image_filename)
                    # 添加原始文件名字段，同時將加密文件名備份
                    if original_image_filename != image_filename:
                        old_product['image_encrypted_filename'] = image_filename  # 備份加密文件名
                        old_product['image_url_original'] = old_product['image_url']  # 備份原始URL
                        
                        # 用於日誌顯示的修改：替換URL中的文件名為原始文件名
                        old_product['image_url'] = original_image_filename
                        old_product['original_image_filename'] = original_image_filename
                        print(f"圖片文件名: {image_filename} -> 原始文件名: {original_image_filename}")
                except Exception as e:
                    print(f"提取圖片原始文件名出錯: {str(e)}")
            
            if old_product.get('dm_url'):
                dm_path = old_product['dm_url']
                dm_filename = os.path.basename(dm_path)
                try:
                    # 尝试提取原始文件名
                    original_dm_filename = extract_original_filename(dm_filename)
                    # 添加原始文件名字段，同時將加密文件名備份
                    if original_dm_filename != dm_filename:
                        old_product['dm_encrypted_filename'] = dm_filename  # 備份加密文件名
                        old_product['dm_url_original'] = old_product['dm_url']  # 備份原始URL
                        
                        # 用於日誌顯示的修改：替換URL中的文件名為原始文件名
                        old_product['dm_url'] = original_dm_filename
                        old_product['original_dm_filename'] = original_dm_filename
                        print(f"文檔文件名: {dm_filename} -> 原始文件名: {original_dm_filename}")
                except Exception as e:
                    print(f"提取文檔原始文件名出錯: {str(e)}")
            
            # 輸出完整的舊數據以便調試
            print(f"更新前的原始數據: {old_product}")
            
            # 檢查是否有新的圖片上傳
            if data.get('image_url') and (old_product.get('image_url_original') and data.get('image_url') != old_product.get('image_url_original')) and '/uploads/' in data.get('image_url', ''):
                # 删除舊的圖片，使用原始的URL（包含加密文件名）
                print(f"檢測到新的圖片URL: {data.get('image_url')}")
                if old_product.get('image_url_original'):  # 使用備份的原始URL進行刪除操作
                    try:
                        # 嘗試多種方式刪除舊文件
                        print(f"準備刪除舊圖片文件: {old_product['image_url_original']}")
                        
                        if USE_AZURE_STORAGE:
                            # 方法1: 使用完整URL
                            delete_result = delete_file(old_product['image_url_original'], product_name=old_product['name'], is_image=True)
                            
                            # 方法2: 如果上面失敗，嘗試提取blob路徑
                            if not delete_result and '/uploads/' in old_product.get('image_url_original', ''):
                                old_image_blob_path = old_product['image_url_original'].split('/uploads/')[-1]
                                delete_result = delete_file(old_image_blob_path, product_name=old_product['name'], is_image=True)
                                
                            # 方法3: 如果都失敗，嘗試直接從URL中提取文件名
                            if not delete_result and old_product.get('image_encrypted_filename'):
                                blob_path = f"{old_product['name']}/{old_product['image_encrypted_filename']}"
                                delete_result = delete_file(blob_path, product_name=old_product['name'], is_image=True)
                        else:
                            # 本地存儲，直接刪除文件
                            delete_file(old_product['image_url_original'], is_image=True)
                            
                        print("舊圖片文件刪除處理完成")
                    except Exception as e:
                        print(f"刪除舊圖片文件時出錯: {str(e)}")
                
                # 檢查URL格式是否異常（比如只有副檔名沒有文件名的情況）
                image_path = data.get('image_url', '')
                if image_path.endswith('/png') or image_path.endswith('/jpg') or image_path.endswith('/jpeg') or image_path.endswith('/gif') or image_path.endswith('/webp'):
                    print(f"檢測到異常的圖片URL格式，使用原URL: {old_product['image_url_original']}")
                    data['image_url'] = old_product['image_url_original']
            
            # 檢查是否有新的DM上傳
            if data.get('dm_url') and data.get('dm_url') != old_product.get('dm_url') and '/uploads/' in data.get('dm_url', ''):
                # 如果有新的DM上傳，刪除舊的DM文件，使用原始的URL（包含加密文件名）
                print(f"檢測到新的DM URL: {data.get('dm_url')}")
                
                # 無論如何都嘗試刪除舊文件，即使沒有dm_url_original
                try:
                    # 嘗試多種方式刪除舊文件
                    print(f"準備刪除舊DM文件")
                    delete_success = False
                    
                    if USE_AZURE_STORAGE:
                        # 優先使用備份的原始URL進行刪除操作
                        if old_product.get('dm_url_original'):
                            print(f"使用原始URL刪除: {old_product['dm_url_original']}")
                            delete_result = delete_file(old_product['dm_url_original'], product_name=old_product['name'], is_image=False)
                            if delete_result:
                                delete_success = True
                                print(f"使用原始URL成功刪除舊DM文件")
                        
                        # 如果沒有原始URL或刪除失敗，嘗試使用dm_url
                        if not delete_success and old_product.get('dm_url'):
                            print(f"使用dm_url刪除: {old_product['dm_url']}")
                            # 如果dm_url包含協議頭，可能是完整的URL
                            if '://' in old_product['dm_url']:
                                delete_result = delete_file(old_product['dm_url'], product_name=old_product['name'], is_image=False)
                                if delete_result:
                                    delete_success = True
                                    print(f"使用dm_url成功刪除舊DM文件")
                            
                            # 如果不是完整URL，可能只是文件名
                            if not delete_success:
                                print(f"嘗試拼接blob路徑")
                                dm_filename = os.path.basename(old_product['dm_url'])
                                blob_path = f"{old_product['name']}/{dm_filename}"
                                delete_result = delete_file(blob_path, product_name=old_product['name'], is_image=False)
                                if delete_result:
                                    delete_success = True
                                    print(f"使用拼接的blob路徑成功刪除舊DM文件")
                        
                        # 如果上面的方法都失敗，嘗試使用dm_encrypted_filename
                        if not delete_success and old_product.get('dm_encrypted_filename'):
                            print(f"使用加密文件名刪除: {old_product['dm_encrypted_filename']}")
                            blob_path = f"{old_product['name']}/{old_product['dm_encrypted_filename']}"
                            delete_result = delete_file(blob_path, product_name=old_product['name'], is_image=False)
                            if delete_result:
                                delete_success = True
                                print(f"使用加密文件名成功刪除舊DM文件")
                        
                        # 最後一個嘗試：從dm_url分解出文件路徑
                        if not delete_success and '/uploads/' in old_product.get('dm_url', ''):
                            print(f"嘗試從dm_url提取blob路徑")
                            old_dm_blob_path = old_product['dm_url'].split('/uploads/')[-1]
                            delete_result = delete_file(old_dm_blob_path, product_name=old_product['name'], is_image=False)
                            if delete_result:
                                delete_success = True
                                print(f"使用提取的blob路徑成功刪除舊DM文件")
                    else:
                        # 本地存儲，直接使用原始URL或dm_url刪除文件
                        if old_product.get('dm_url_original'):
                            delete_file(old_product['dm_url_original'], is_image=False)
                        elif old_product.get('dm_url'):
                            delete_file(old_product['dm_url'], is_image=False)
                        
                    print("舊DM文件刪除處理完成")
                except Exception as e:
                    print(f"刪除舊DM文件時出錯: {str(e)}")
                
                # 檢查URL格式是否異常
                dm_path = data.get('dm_url', '')
                if dm_path.endswith('/pdf') or dm_path.endswith('/doc') or dm_path.endswith('/docx') or dm_path.endswith('/xls') or dm_path.endswith('/xlsx') or dm_path.endswith('/ppt') or dm_path.endswith('/pptx'):
                    print(f"檢測到異常的DM URL格式，使用原URL: {old_product['dm_url_original']}")
                    data['dm_url'] = old_product['dm_url_original']
            
            # 檢查產品名稱是否有變更，若有則需要處理文件夾重命名
            if data.get('name') and data.get('name') != old_product['name']:
                print(f"產品名稱已變更：從 {old_product['name']} 到 {data.get('name')}")
                
                # 對於Azure存儲，需要移動所有文件到新的產品名稱文件夾
                if USE_AZURE_STORAGE:
                    try:
                        # 這裡只處理重新上傳和更新數據庫中的路徑，Azure無法直接重命名文件夾
                        print("使用Azure存儲，將在新上傳時使用新產品名稱作為路徑")
                        # 將來如果需要實現文件移動，可以在這裡添加代碼
                    except Exception as e:
                        print(f"處理Azure存儲產品名稱變更時出錯: {str(e)}")
                else:
                    # 本地存儲處理文件夾重命名
                    try:
                        old_folder = os.path.join(UPLOAD_FOLDER, secure_filename(old_product['name']))
                        new_folder = os.path.join(UPLOAD_FOLDER, secure_filename(data.get('name')))
                        
                        if os.path.exists(old_folder) and os.path.isdir(old_folder):
                            # 如果新文件夾已存在，先刪除它
                            if os.path.exists(new_folder):
                                print(f"新文件夾已存在，刪除: {new_folder}")
                                shutil.rmtree(new_folder)
                                
                            # 重命名文件夾
                            print(f"重命名文件夾: {old_folder} -> {new_folder}")
                            os.rename(old_folder, new_folder)
                            
                            # 更新URL中的文件夾名稱
                            if data.get('image_url') and '/uploads/' in data.get('image_url'):
                                old_path = f"/uploads/{secure_filename(old_product['name'])}"
                                new_path = f"/uploads/{secure_filename(data.get('name'))}"
                                data['image_url'] = data['image_url'].replace(old_path, new_path)
                                print(f"更新圖片URL: {data['image_url']}")
                                
                            if data.get('dm_url') and '/uploads/' in data.get('dm_url'):
                                old_path = f"/uploads/{secure_filename(old_product['name'])}"
                                new_path = f"/uploads/{secure_filename(data.get('name'))}"
                                data['dm_url'] = data['dm_url'].replace(old_path, new_path)
                                print(f"更新DM URL: {data['dm_url']}")
                        else:
                            print(f"舊產品文件夾不存在: {old_folder}")
                    except Exception as e:
                        print(f"重命名產品文件夾時出錯: {str(e)}")
            
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
            
            # 處理原始文件名：只在有新文件時更新原始文件名字段
            # 檢查圖片URL是否發生了變化
            if 'image_url' in data and data.get('image_url') != old_product.get('image_url'):
                print(f"圖片URL發生了變化，使用新的原始文件名: {data.get('image_original_filename', '')}")
                filtered_data['image_original_filename'] = data.get('image_original_filename', '')
            else:
                print(f"圖片URL未變化，保留原始文件名: {old_product.get('image_original_filename', '')}")
                # 從資料庫獲取原始的檔案名
                cursor = conn.cursor()
                cursor.execute("SELECT image_original_filename FROM products WHERE id = %s", (product_id,))
                result = cursor.fetchone()
                if result and result[0]:
                    filtered_data['image_original_filename'] = result[0]
                else:
                    filtered_data['image_original_filename'] = old_product.get('image_original_filename', '') or old_product.get('original_image_filename', '')
            
            # 檢查文檔URL是否發生了變化
            if 'dm_url' in data and data.get('dm_url') != old_product.get('dm_url'):
                print(f"文檔URL發生了變化，使用新的原始文件名: {data.get('dm_original_filename', '')}")
                filtered_data['dm_original_filename'] = data.get('dm_original_filename', '')
            else:
                print(f"文檔URL未變化，保留原始文件名: {old_product.get('dm_original_filename', '')}")
                # 從資料庫獲取原始的檔案名
                cursor = conn.cursor()
                cursor.execute("SELECT dm_original_filename FROM products WHERE id = %s", (product_id,))
                result = cursor.fetchone()
                if result and result[0]:
                    filtered_data['dm_original_filename'] = result[0]
                else:
                    filtered_data['dm_original_filename'] = old_product.get('dm_original_filename', '') or old_product.get('original_dm_filename', '')
            
            # 打印最終要更新的數據
            print(f"最終更新數據: {filtered_data}")
            
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
            
            # 如果沒有提供產品文件夾名稱，則使用產品名稱
            if not product_folder and product.get('name'):
                product_folder = product.get('name')
            
            # 嘗試刪除uploads文件夾
            if product_folder:
                try:
                    print(f"嘗試刪除產品文件夾: {product_folder}")
                    # 使用產品名稱作為文件夾名稱
                    folder_name = secure_filename(product_folder)
                    
                    if USE_AZURE_STORAGE:
                        # 對於Azure存儲，需要列出並刪除所有blob
                        from backend.utils.azure_storage import list_product_files
                        product_files = list_product_files(folder_name)
                        if product_files:
                            print(f"找到Azure存儲中的{len(product_files)}個文件需要刪除")
                            for file_info in product_files:
                                try:
                                    # 從文件URL中提取blob路徑
                                    blob_name = file_info.get('name')
                                    if blob_name:
                                        print(f"刪除Azure blob: {blob_name}")
                                        delete_file(blob_name, product_name=product_folder)
                                except Exception as e:
                                    print(f"刪除Azure blob時出錯: {str(e)}")
                            print("已刪除所有產品相關的Azure存儲文件")
                        else:
                            print(f"Azure存儲中找不到產品文件夾: {folder_name}")
                    else:
                        # 本地存儲刪除
                        delete_folder_result = remove_product_folder(folder_name)
                        print(f"刪除產品文件夾結果: {delete_folder_result}")
                except Exception as e:
                    print(f"刪除產品文件夾時出錯: {str(e)}")
            
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
        
        print(f"收到圖片上傳請求，產品名稱: {product_name}, 檔案名: {file.filename}, 檔案類型: {file.content_type}")
        
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
            print(f"圖片文件名處理: 原始={original_filename}, 安全文件名={safe_filename}")
            
            if USE_AZURE_STORAGE:
                # 使用Azure Blob存儲
                # 刪除之前的圖片
                existing_files = get_product_files(product_name, is_image=True)
                for existing_file in existing_files:
                    try:
                        delete_file(existing_file['name'])
                        print(f"已刪除舊圖片文件: {existing_file['filename']}")
                    except Exception as e:
                        print(f"刪除舊圖片時出錯: {str(e)}")
                
                # 保存新上傳的文件到Azure
                print(f"開始上傳圖片到Azure，產品名: {product_name}")
                file_path = save_file(file, product_name, is_image=True)
                
                if not file_path:
                    return jsonify({
                        'status': 'error',
                        'message': 'Failed to upload file to Azure'
                    }), 500
                
                print(f"圖片上傳成功，Azure路徑: {file_path}，原始文件名: {original_filename}")
                return jsonify({
                    'status': 'success',
                    'data': {
                        'file_path': file_path,
                        'original_filename': original_filename
                    }
                })
            else:
                # 本地存儲
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
                
                print(f"圖片上傳成功，完整路徑: {relative_path}，原始文件名: {original_filename}")
                return jsonify({
                    'status': 'success',
                    'data': {
                        'file_path': f'/{relative_path.replace(os.sep, "/")}',
                        'original_filename': original_filename  # 返回原始文件名
                    }
                })
        else:
            print(f"不支持的圖片類型: {file.filename}，文件內容類型: {file.content_type}")
            return jsonify({
                'status': 'error',
                'message': f'不支持的圖片類型: {file.filename}'
            }), 400
    except Exception as e:
        print(f"Error in upload_image: {str(e)}")
        import traceback
        traceback.print_exc()
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
        
        print(f"處理文件 - 名稱: {file.filename}, 內容類型: {file.content_type}")
        
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': 'No selected file'
            }), 400
            
        if file and allowed_doc_file(file.filename):
            # 保存原始文件名
            original_filename = file.filename
            
            # 创建安全文件名
            safe_filename = create_dual_filename(original_filename)
            print(f"原始文件名: {original_filename} -> 雙軌文件名: {safe_filename}")
            
            if USE_AZURE_STORAGE:
                # 使用Azure Blob存儲
                # 刪除產品之前的DM文件，確保更新產品時能正確刪除舊文件
                existing_files = get_product_files(product_name, is_image=False)
                delete_count = 0
                for existing_file in existing_files:
                    try:
                        result = delete_file(existing_file['name'], product_name=product_name, is_image=False)
                        if result:
                            delete_count += 1
                            print(f"已刪除舊DM文件: {existing_file['filename']}")
                    except Exception as e:
                        print(f"刪除舊DM文件時出錯: {str(e)}")
                
                print(f"已刪除 {delete_count} 個舊DM文件")
                
                # 保存新上傳的文件到Azure
                file_path = save_file(file, product_name, is_image=False)
                
                if not file_path:
                    return jsonify({
                        'status': 'error',
                        'message': 'Failed to upload document to Azure'
                    }), 500
                
                print(f"文檔上傳成功，Azure路徑: {file_path}，原始文件名: {original_filename}")
                return jsonify({
                    'status': 'success',
                    'data': {
                        'file_path': file_path,
                        'original_filename': original_filename
                    }
                })
            else:
                # 本地存儲
                product_folder = create_product_folder(product_name)
                filepath = os.path.join(product_folder, safe_filename)
                
                # 刪除現有的文檔文件（與圖片處理類似）
                doc_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt']
                delete_count = 0
                for existing_file in os.listdir(product_folder):
                    file_ext = os.path.splitext(existing_file)[1].lower()
                    if file_ext in doc_extensions:
                        try:
                            os.remove(os.path.join(product_folder, existing_file))
                            delete_count += 1
                            print(f"已刪除舊文檔文件: {existing_file}")
                        except Exception as e:
                            print(f"刪除舊文檔文件時出錯: {str(e)}")
                            
                print(f"已刪除 {delete_count} 個舊文檔文件")
                            
                # 保存新上傳的文件
                file.save(filepath)
                
                # 返回相对路径
                relative_path = os.path.join('uploads', secure_filename(product_name), safe_filename)
                
                print(f"文件上傳成功，完整路徑: {relative_path}，原始文件名: {original_filename}")
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
                RETURNING id, locked_date
            """, (data['date'],))
            
            result = cursor.fetchone()
            new_id = result[0]
            locked_date = result[1]
            conn.commit()
            
            # 记录操作日誌
            try:
                admin_id = get_admin_id_from_session()
                
                if admin_id:
                    # 确保锁定日期是字符串格式
                    locked_date_str = locked_date.strftime('%Y-%m-%d') if hasattr(locked_date, 'strftime') else str(locked_date)
                    
                    # 创建日志记录
                    log_service = LogServiceRegistry.get_service(conn, 'products')
                    log_service.log_operation(
                        table_name='products',
                        operation_type='新增',
                        record_id=new_id,
                        old_data=None,
                        new_data={'id': new_id, 'locked_date': locked_date_str, 'record_type': '锁定日期'},
                        performed_by=admin_id,
                        user_type='管理員'
                    )
                    print(f"已記錄鎖定日期操作: {locked_date_str}")
            except Exception as log_error:
                print(f"記錄鎖定日期日誌時出錯: {str(log_error)}")
                # 继续执行，不要因为日志记录失败而中断主流程
            
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

def get_admin_id_from_session():
    """从会话中获取管理员ID"""
    try:
        # 从cookie或session中获取admin_id
        admin_id = request.cookies.get('admin_id') or session.get('admin_id')
        if not admin_id:
            # 尝试从请求数据中获取
            admin_id = request.json.get('admin_id')
        return int(admin_id) if admin_id else None
    except Exception as e:
        print(f"获取管理员ID时出错: {str(e)}")
        return None

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
            
            # 获取日期信息用于日志
            cursor.execute("""
                SELECT id, locked_date FROM locked_dates
                WHERE id = %s
            """, (data['date_id'],))
            
            date_info = cursor.fetchone()
            if not date_info:
                return jsonify({
                    'status': 'error',
                    'message': '找不到该锁定日期'
                }), 404
                
            date_id = date_info[0]
            locked_date = date_info[1]
            
            # 删除锁定日期
            cursor.execute("""
                DELETE FROM locked_dates
                WHERE id = %s
            """, (data['date_id'],))
            
            conn.commit()
            
            # 记录操作日誌
            try:
                admin_id = get_admin_id_from_session()
                
                if admin_id:
                    # 确保锁定日期是字符串格式
                    locked_date_str = locked_date.strftime('%Y-%m-%d') if hasattr(locked_date, 'strftime') else str(locked_date)
                    
                    # 创建日志记录
                    log_service = LogServiceRegistry.get_service(conn, 'products')
                    log_service.log_operation(
                        table_name='products',
                        operation_type='刪除',
                        record_id=date_id,
                        old_data={'id': date_id, 'locked_date': locked_date_str, 'record_type': '锁定日期'},
                        new_data=None,
                        performed_by=admin_id,
                        user_type='管理員'
                    )
                    print(f"已記錄解鎖日期操作: {locked_date_str}")
            except Exception as log_error:
                print(f"記錄解鎖日期日誌時出錯: {str(log_error)}")
                # 继续执行，不要因为日志记录失败而中断主流程
            
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

@product_bp.route('/products/clean-expired-dates', methods=['POST'])
def clean_expired_dates_route():
    """手动触发清理过期锁定日期的API"""
    try:
        data = request.json
        if not data.get('type') == 'admin':
            return jsonify({
                'status': 'error',
                'message': 'Unauthorized access'
            }), 403
            
        # 执行清理
        result = run_clean_task_manually()
        return jsonify(result)
            
    except Exception as e:
        print(f"Error in clean_expired_dates: {str(e)}")
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
            
            # 直接从数据库中获取原始文件名
            cursor = conn.cursor()
            cursor.execute("""
                SELECT image_original_filename, dm_original_filename 
                FROM products 
                WHERE id = %s
            """, (product_id,))
            
            result = cursor.fetchone()
            if result:
                if result[0]:  # 图片原始文件名
                    product['original_image_filename'] = result[0]
                    product['image_original_filename'] = result[0]
                
                if result[1]:  # 文档原始文件名
                    product['original_dm_filename'] = result[1]
                    product['dm_original_filename'] = result[1]
            
            # 如果数据库没有原始文件名，尝试从文件名中提取
            if product.get('image_url') and not product.get('original_image_filename'):
                image_path = product['image_url']
                image_filename = os.path.basename(image_path)
                try:
                    # 尝试提取原始文件名
                    original_image_filename = extract_original_filename(image_filename)
                    # 替换路径中的文件名部分
                    if original_image_filename != image_filename:
                        product['original_image_filename'] = original_image_filename
                        product['image_original_filename'] = original_image_filename
                    print(f"图片文件名: {image_filename} -> 原始文件名: {original_image_filename}")
                except Exception as e:
                    print(f"提取图片原始文件名出错: {str(e)}")
            
            if product.get('dm_url') and not product.get('original_dm_filename'):
                dm_path = product['dm_url']
                dm_filename = os.path.basename(dm_path)
                try:
                    # 尝试提取原始文件名
                    original_dm_filename = extract_original_filename(dm_filename)
                    # 替换路径中的文件名部分
                    if original_dm_filename != dm_filename:
                        product['original_dm_filename'] = original_dm_filename
                        product['dm_original_filename'] = original_dm_filename
                        print(f"文档文件名: {dm_filename} -> 原始文件名: {original_dm_filename}")
                except Exception as e:
                    print(f"提取文档原始文件名出错: {str(e)}")
            
            # 确保返回所有版本的原始文件名字段
            if product.get('original_image_filename') and not product.get('image_original_filename'):
                product['image_original_filename'] = product['original_image_filename']
            elif product.get('image_original_filename') and not product.get('original_image_filename'):
                product['original_image_filename'] = product['image_original_filename']
                
            if product.get('original_dm_filename') and not product.get('dm_original_filename'):
                product['dm_original_filename'] = product['original_dm_filename']
            elif product.get('dm_original_filename') and not product.get('original_dm_filename'):
                product['original_dm_filename'] = product['dm_original_filename']
            
            print(f"返回产品详情数据，原始文件名信息：图片={product.get('original_image_filename', '')}, 文档={product.get('original_dm_filename', '')}")
            
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

@product_bp.route('/azure-blob/download', methods=['GET'])
def download_azure_blob():
    """從Azure Blob下載文件並保留原始文件名"""
    try:
        # 獲取必要的參數
        blob_url = request.args.get('url')
        original_filename = request.args.get('filename')
        
        if not blob_url or not original_filename:
            return jsonify({
                'status': 'error',
                'message': 'Missing blob URL or original filename'
            }), 400
        
        print(f"準備下載的文件: URL={blob_url}, 原始檔名={original_filename}")
        
        # 正確解析Azure Blob URL
        from urllib.parse import urlparse, unquote, quote
        parsed_url = urlparse(blob_url)
        
        # 檢查是否需要進行URL解碼（避免多重編碼問題）
        if '%25' in blob_url:
            # 檢測到已經被雙重編碼的URL，需要解碼一次
            blob_url = unquote(blob_url)
            parsed_url = urlparse(blob_url)
            print(f"URL解碼後: {blob_url}")
        
        # 獲取容器名稱和blob路徑
        path_parts = parsed_url.path.lstrip('/').split('/')
        
        if len(path_parts) < 2:
            return jsonify({
                'status': 'error',
                'message': 'Invalid blob URL format'
            }), 400
        
        container = path_parts[0]  # 第一部分是容器名稱
        blob_path = '/'.join(path_parts[1:])  # 其餘部分組成blob路徑
        
        print(f"解析後的容器: {container}, Blob路徑: {blob_path}")
        
        # 連接到Azure服務
        from backend.utils.azure_storage import get_blob_service_client
        
        try:
            client = get_blob_service_client()
            blob_client = client.get_blob_client(container=container, blob=blob_path)
            
            # 檢查blob是否存在
            if not blob_client.exists():
                print(f"文件不存在，嘗試使用未進行URL編碼的路徑")
                # 嘗試使用未進行URL編碼的路徑
                blob_path = unquote(blob_path)
                blob_client = client.get_blob_client(container=container, blob=blob_path)
                
                if not blob_client.exists():
                    print(f"blob不存在: {container}/{blob_path}")
                    return jsonify({
                        'status': 'error',
                        'message': 'File not found'
                    }), 404
            
            # 獲取Blob數據
            print(f"開始下載blob: {container}/{blob_path}")
            blob_data = blob_client.download_blob()
            
            # 創建響應
            response = make_response(blob_data.readall())
            
            # 設置Content-Type和Content-Disposition標頭
            content_type = 'application/octet-stream'
            disposition = 'attachment'  # 默認為下載
            
            # 根據文件類型設定正確的Content-Type
            if original_filename.lower().endswith('.pdf'):
                content_type = 'application/pdf'
                disposition = 'inline'  # PDF使用inline在瀏覽器中預覽
            elif original_filename.lower().endswith(('.doc', '.docx')):
                content_type = 'application/msword'
            elif original_filename.lower().endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
                disposition = 'inline'
            elif original_filename.lower().endswith('.png'):
                content_type = 'image/png'
                disposition = 'inline'
            
            print(f"文件類型: {content_type}, 處理方式: {disposition}")
            
            # 針對非ASCII字符的文件名進行處理
            # 使用RFC 5987編碼方式以支持UTF-8文件名，對所有文件類型都適用
            ascii_filename = original_filename.encode('ascii', 'ignore').decode()
            encoded_filename = quote(original_filename)
            
            # 不管是inline還是attachment，都設置filename*參數確保原始檔名可用
            if disposition == 'inline':
                # 預覽模式 - 確保下載時也有正確檔名
                response.headers['Content-Disposition'] = f'inline; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            else:
                # 下載模式
                response.headers['Content-Disposition'] = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}'
            
            response.headers['Content-Type'] = content_type
            
            print(f"文件下載響應頭: {response.headers}")
            return response
            
        except Exception as blob_error:
            print(f"訪問或下載blob時出錯: {str(blob_error)}")
            import traceback
            traceback.print_exc()
            
            # 嘗試重定向到原始URL以便直接預覽
            if original_filename.lower().endswith('.pdf'):
                print(f"嘗試重定向到原始URL進行預覽: {blob_url}")
                return redirect(blob_url)
            
            return jsonify({
                'status': 'error',
                'message': f'無法下載文件: {str(blob_error)}'
            }), 500
            
    except Exception as e:
        print(f"下載Azure Blob時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500 