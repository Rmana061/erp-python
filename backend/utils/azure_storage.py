import os
import logging
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, generate_blob_sas
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
import uuid
from werkzeug.utils import secure_filename
from urllib.parse import urlparse

# 從環境變數獲取連接字符串
connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
container_name = os.getenv('AZURE_STORAGE_CONTAINER', 'uploads')

def get_blob_service_client():
    """獲取Blob服務客戶端"""
    try:
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        logging.error(f"無法連接到Azure Blob存儲: {str(e)}")
        raise

def ensure_container_exists():
    """確保容器存在，如果不存在則創建"""
    try:
        client = get_blob_service_client()
        container_client = client.get_container_client(container_name)
        
        # 檢查容器是否存在
        try:
            container_client.get_container_properties()
        except ResourceNotFoundError:
            # 容器不存在，創建它
            container_client.create_container(public_access="blob")
            logging.info(f"創建了容器: {container_name}")
    
    except Exception as e:
        logging.error(f"確保容器存在時出錯: {str(e)}")
        raise

def upload_file_to_blob(file, filename, product_name, is_image=True):
    """上傳文件到Azure Blob存儲
    
    Args:
        file: 文件對象
        filename: 文件名
        product_name: 產品名稱，用於文件夾路徑
        is_image: 是否為圖片文件，決定使用哪個子文件夾
    
    Returns:
        blob_url: 完整的Blob URL
    """
    try:
        ensure_container_exists()
        
        # 獲取文件的內容類型
        content_type = file.content_type
        logging.info(f"上傳文件: {filename}, 內容類型: {content_type}")
        
        # 確保文件名有正確的副檔名
        file_base, file_ext = os.path.splitext(filename)
        
        # 如果沒有副檔名或副檔名不匹配內容類型，根據內容類型添加
        if not file_ext or file_ext == '.':
            # 根據內容類型添加副檔名
            if 'jpeg' in content_type or 'jpg' in content_type:
                file_ext = '.jpg'
            elif 'png' in content_type:
                file_ext = '.png'
            elif 'gif' in content_type:
                file_ext = '.gif'
            elif 'pdf' in content_type:
                file_ext = '.pdf'
            elif 'msword' in content_type:
                file_ext = '.doc'
            elif 'openxmlformats-officedocument.wordprocessingml.document' in content_type:
                file_ext = '.docx'
            elif 'openxmlformats-officedocument.spreadsheetml.sheet' in content_type:
                file_ext = '.xlsx'
            elif 'vnd.ms-excel' in content_type:
                file_ext = '.xls'
            else:
                # 如果無法從內容類型確定，根據文件是圖片或文檔添加默認副檔名
                if is_image:
                    file_ext = '.jpg'  # 默認圖片為jpg
                else:
                    file_ext = '.pdf'  # 默認文檔為pdf
            
            # 組合新的文件名
            filename = f"{file_base}{file_ext}"
            logging.info(f"已添加副檔名: {filename}")
        
        # 檢查文件名是否只有副檔名（如：只有"png"而不是"image.png"）
        if file_base == '':
            # 如果只有副檔名，添加UUID作為文件名
            filename = f"{uuid.uuid4()}{file_ext}"
            logging.info(f"文件名只有副檔名，已添加UUID: {filename}")
        
        # 特殊處理jpg/jpeg文件，防止URL問題
        if is_image and (filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg')):
            # 檢查是否看起來像URL
            if '://' in filename or filename.startswith('http'):
                # 如果檔名是URL，創建一個新的UUID檔名
                new_filename = f"{uuid.uuid4()}.jpg"
                logging.info(f"JPG文件名看起來像URL，已修正: {filename} -> {new_filename}")
                filename = new_filename
        
        # 使用安全的文件名（避免特殊字符）
        safe_filename = secure_filename(filename)
        if safe_filename != filename:
            logging.info(f"文件名已安全處理: {filename} -> {safe_filename}")
            filename = safe_filename
        
        # 使用類似本地存儲的路徑結構
        # 如果是圖片，直接放在產品文件夾下
        # 如果是文檔，也直接放在產品文件夾下（與本地存儲保持一致）
        blob_path = f"{product_name}/{filename}"
        
        # 獲取blob客戶端
        client = get_blob_service_client()
        blob_client = client.get_blob_client(container=container_name, blob=blob_path)
        
        # 上傳文件
        file.seek(0)  # 確保從文件開頭讀取
        
        # 設置內容類型
        content_type = get_content_type_from_filename(filename)
        
        # 上傳文件，設置內容類型
        blob_client.upload_blob(
            file, 
            overwrite=True,
            content_type=content_type
        )
        
        # 打印詳細信息以便調試
        logging.info(f"文件已上傳到Azure Blob，路徑: {blob_path}, 內容類型: {content_type}")
        
        # 返回完整URL
        return blob_client.url
    
    except Exception as e:
        logging.error(f"上傳文件到Azure Blob時出錯: {str(e)}")
        raise

def get_content_type_from_filename(filename):
    """根據文件名獲取內容類型"""
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext == '.jpg' or file_ext == '.jpeg':
        return 'image/jpeg'
    elif file_ext == '.png':
        return 'image/png'
    elif file_ext == '.gif':
        return 'image/gif'
    elif file_ext == '.pdf':
        return 'application/pdf'
    elif file_ext == '.doc':
        return 'application/msword'
    elif file_ext == '.docx':
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif file_ext == '.xls':
        return 'application/vnd.ms-excel'
    elif file_ext == '.xlsx':
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        return 'application/octet-stream'  # 默認二進制數據類型

def delete_blob(blob_path):
    """刪除blob
    
    Args:
        blob_path: blob的完整路徑，例如 'product_name/filename.jpg'
    """
    try:
        client = get_blob_service_client()
        
        # 檢查blob_path是否是完整URL或相對路徑
        if blob_path.startswith('http'):
            # 是完整URL，需要提取blob路徑
            parsed_url = urlparse(blob_path)
            path_parts = parsed_url.path.lstrip('/').split('/')
            
            if len(path_parts) >= 2:
                # 第一部分是容器名，其餘部分是blob路徑
                container = path_parts[0]
                blob_name = '/'.join(path_parts[1:])
                
                # 確認容器名與配置匹配
                if container != container_name:
                    logging.warning(f"警告：URL中的容器名 '{container}' 與配置的容器名 '{container_name}' 不匹配")
                
                # 使用提取的blob路徑
                blob_client = client.get_blob_client(container=container_name, blob=blob_name)
                logging.info(f"從URL提取的blob路徑: {blob_name}")
            else:
                raise ValueError(f"無法從URL中提取有效的blob路徑: {blob_path}")
        else:
            # 直接使用提供的路徑
            blob_client = client.get_blob_client(container=container_name, blob=blob_path)
            logging.info(f"使用直接提供的blob路徑: {blob_path}")
        
        # 檢查blob是否存在
        if blob_client.exists():
            blob_client.delete_blob()
            logging.info(f"成功刪除blob: {blob_path}")
        else:
            logging.warning(f"要刪除的blob不存在: {blob_path}")
            
    except Exception as e:
        logging.error(f"刪除blob時出錯: {str(e)}")
        # 不拋出異常，避免影響主流程
        logging.exception("詳細錯誤信息:")
        return False
    
    return True

def generate_sas_url(blob_path, expiry_hours=1):
    """生成SAS URL，用於有時限的訪問私有blob
    
    Args:
        blob_path: blob的完整路徑，例如 'product_name/filename.jpg'
        expiry_hours: SAS令牌的有效期（小時）
    
    Returns:
        sas_url: 帶有SAS令牌的完整URL
    """
    try:
        client = get_blob_service_client()
        blob_client = client.get_blob_client(container=container_name, blob=blob_path)
        
        # 生成SAS令牌
        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=container_name,
            blob_name=blob_path,
            account_key=client.credential.account_key,
            permission="r",  # 讀取權限
            expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
        )
        
        # 返回帶有SAS令牌的URL
        return f"{blob_client.url}?{sas_token}"
    
    except Exception as e:
        logging.error(f"生成SAS URL時出錯: {str(e)}")
        raise

def list_product_files(product_name):
    """列出特定產品的所有文件
    
    Args:
        product_name: 產品名稱
    
    Returns:
        list: 文件信息的列表
    """
    try:
        client = get_blob_service_client()
        container_client = client.get_container_client(container_name)
        
        # 列出所有帶有指定前綴的blob
        prefix = f"{product_name}/"
        blob_list = []
        
        for blob in container_client.list_blobs(name_starts_with=prefix):
            blob_client = container_client.get_blob_client(blob.name)
            
            # 判斷文件類型
            filename = blob.name.replace(prefix, "")
            is_image = filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
            
            blob_list.append({
                "name": blob.name,  # 完整路徑
                "filename": filename,  # 僅文件名部分
                "url": blob_client.url,
                "size": blob.size,
                "last_modified": blob.last_modified,
                "is_image": is_image
            })
        
        return blob_list
    
    except Exception as e:
        logging.error(f"列出blob時出錯: {str(e)}")
        raise 