import os
import uuid
import mimetypes
from werkzeug.utils import secure_filename
import logging
from .azure_storage import upload_file_to_blob, delete_blob, list_product_files

# 獲取 logger
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_DOC_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt'}

# 是否使用Azure Blob存儲
USE_AZURE_STORAGE = os.getenv('AZURE_STORAGE_CONNECTION_STRING') is not None

def create_product_folder(product_name):
    """創建產品文件夾 (僅在本地儲存時使用)"""
    if not USE_AZURE_STORAGE:
        folder_path = os.path.join(UPLOAD_FOLDER, secure_filename(product_name))
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        return folder_path
    return None  # 使用Azure時不需要創建本地文件夾

def get_file_extension(filename):
    """從文件名獲取擴展名"""
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

def is_allowed_image(filename):
    """檢查是否為允許的圖片類型"""
    return get_file_extension(filename) in ALLOWED_IMAGE_EXTENSIONS

def is_allowed_document(filename):
    """檢查是否為允許的文檔類型"""
    return get_file_extension(filename) in ALLOWED_DOC_EXTENSIONS

def save_file(file, product_name, is_image=True):
    """儲存文件（到本地或Azure）
    
    Args:
        file: 文件對象
        product_name: 產品名稱
        is_image: 是否為圖片文件
    
    Returns:
        file_path: 文件路徑或URL
    """
    try:
        if file.filename == '':
            return None
        
        # 獲取文件的MIME類型
        content_type = file.content_type
        logger.debug("處理文件 - 名稱: %s, 內容類型: %s", file.filename, content_type)
        
        # 安全處理文件名
        filename = secure_filename(file.filename)
        
        # 嘗試從content_type獲取擴展名
        extension = mimetypes.guess_extension(content_type)
        if extension:
            filename = f"{os.path.splitext(filename)[0]}{extension}"
            logger.debug("從content_type獲取擴展名: %s, 新文件名: %s", extension, filename)
        else:
            # 如果無法從content_type獲取，使用原文件的擴展名
            extension = get_file_extension(filename)
            if not extension:
                extension = '.bin'  # 默認擴展名
                filename = f"{filename}{extension}"
            logger.debug("使用預設擴展名: %s, 新文件名: %s", extension, filename)

        # 檢查文件類型
        if is_image and not is_allowed_image(filename):
            logger.warning("不支持的圖片類型: %s", filename)
            return None
        elif not is_image and not is_allowed_document(filename):
            logger.warning("不支持的文檔類型: %s", filename)
            return None
        
        # 使用雙軌文件名處理所有文件名
        from backend.routes.product_routes import create_dual_filename
        dual_filename = create_dual_filename(filename)
        logger.debug("原始文件名: %s -> 雙軌文件名: %s", filename, dual_filename)
        filename = dual_filename
        
        # 根據配置選擇存儲方式
        if USE_AZURE_STORAGE:
            # 使用Azure Blob存儲
            # 在Azure中，我們使用單一容器，產品名稱作為"資料夾"前綴
            safe_product_name = secure_filename(product_name)
            
            # 確保文件名不會被截斷為URL
            # 特別檢查如果是jpg圖片，確保文件名正確
            if is_image and filename.lower().endswith(('.jpg', '.jpeg')):
                # 確保文件名有效，不是URL
                if '://' in filename or filename.startswith('http'):
                    # 如果檔名看起來像URL，則使用UUID生成新檔名
                    filename = f"{uuid.uuid4()}.jpg"
                    logger.warning("檔名看起來像URL，已重新生成: %s", filename)
            
            # 上傳到Azure
            return upload_file_to_blob(file, filename, safe_product_name, is_image)
        else:
            # 使用本地存儲
            folder_path = create_product_folder(product_name)
            file_path = os.path.join(folder_path, filename)
            file.save(file_path)
            return file_path

    except Exception as e:
        logger.error("保存文件時發生錯誤: %s", str(e))
        return None

def delete_file(file_path, product_name=None, is_image=True):
    """刪除文件（從本地或Azure）
    
    Args:
        file_path: 完整的文件路徑或blob路徑
        product_name: 產品名稱（僅Azure使用）
        is_image: 是否為圖片文件（僅本地使用）
        
    Returns:
        bool: 是否成功刪除文件
    """
    try:
        if USE_AZURE_STORAGE:
            # Azure中的blob刪除
            return delete_blob(file_path)
        else:
            # 本地文件刪除
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            else:
                logger.warning("要刪除的文件不存在: %s", file_path)
                return False
    except Exception as e:
        logger.error("刪除文件時發生錯誤: %s", str(e))
        return False

def get_product_files(product_name, is_image=None):
    """獲取產品的所有文件
    
    Args:
        product_name: 產品名稱
        is_image: 如果是None則獲取所有文件，True只獲取圖片，False只獲取文檔
    
    Returns:
        list: 文件路徑或URL的列表
    """
    if USE_AZURE_STORAGE:
        # 從Azure獲取文件列表
        all_files = list_product_files(secure_filename(product_name))
        
        # 根據is_image篩選
        if is_image is None:
            return all_files
        else:
            return [f for f in all_files if f['is_image'] == is_image]
    else:
        # 從本地獲取文件列表
        folder_path = os.path.join(UPLOAD_FOLDER, secure_filename(product_name))
        if not os.path.exists(folder_path):
            return []
            
        files = []
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            is_file_image = is_allowed_image(filename)
            
            if is_image is None or (is_image and is_file_image) or (not is_image and not is_file_image and is_allowed_document(filename)):
                files.append({
                    "name": f"{secure_filename(product_name)}/{filename}",
                    "filename": filename,
                    "url": file_path,
                    "is_image": is_file_image
                })
                
        return files 