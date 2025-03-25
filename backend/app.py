import os
import sys
from dotenv import load_dotenv
import base64
import urllib.parse
import atexit  # 添加atexit模块
import logging
from logging.handlers import RotatingFileHandler

# 配置日誌系統
def setup_logging():
    """配置日誌系統"""
    # 創建 logs 目錄
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置根日誌記錄器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 配置日誌格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 配置文件處理器
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # 配置控制台處理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 設置 Werkzeug 日誌級別
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    
    return root_logger

# 初始化日誌系統
logger = setup_logging()

# 載入環境變數
load_dotenv()

# 將專案根目錄添加到 Python 路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, session, send_from_directory
from flask_cors import CORS
from backend.routes.product_routes import product_bp, UPLOAD_FOLDER
from backend.routes.auth_routes import auth_bp
from backend.routes.customer_routes import customer_bp
from backend.routes.admin_routes import admin_bp
from backend.routes.order_routes import order_bp
from backend.routes.line_bot_routes import line_bot_bp
from backend.routes.log_routes import log_bp
from backend.routes.order_check_routes import order_check_bp
from backend.config.database import get_db_connection
from backend.utils.scheduler import initialize_scheduler, shutdown_scheduler  # 導入調度器函數  

# 定義從雙軌文件名中提取原始文件名的函數
def extract_original_filename(dual_filename):
    """從雙軌文件名中提取原始文件名"""
    try:
        # 分離文件名和擴展名
        file_name, file_ext = os.path.splitext(dual_filename)
        # 分離UUID和編碼部分
        parts = file_name.split('___')
        if len(parts) > 1:
            # 解碼原始文件名
            original_name = base64.urlsafe_b64decode(parts[1].encode()).decode()
            return f"{original_name}{file_ext}"
        return dual_filename
    except:
        return dual_filename  # 如果解析失敗，返回原文件名

app = Flask(__name__, static_folder=None)

# Session 配置
app.secret_key = os.getenv('SESSION_SECRET_KEY')
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None',
    PERMANENT_SESSION_LIFETIME=1800,
    SESSION_COOKIE_NAME=os.getenv('SESSION_COOKIE_NAME', 'erp_session')
)

# CORS 配置
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv('ALLOWED_ORIGINS').split(',')]
CORS(app, 
     supports_credentials=True,
     origins=ALLOWED_ORIGINS,
     allow_headers=['Content-Type', 'Authorization', 'X-Customer-ID', 'X-Company-Name', 'X-Requested-With'],
     expose_headers=['Set-Cookie'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

# 在每個請求前檢查 session 和 Authorization
@app.before_request
def before_request():
    if request.method == 'OPTIONS':
        return

    logger.info("當前 session: %s", dict(session))
    logger.info("請求路徑: %s", request.path)
    logger.info("請求方法: %s", request.method)
    logger.info("Cookie: %s", request.cookies)
    logger.info("Origin: %s", request.headers.get('Origin'))
    logger.info("Authorization: %s", request.headers.get('Authorization'))
    
    # 記錄前端傳遞的自定義頭部
    customer_id = request.headers.get('X-Customer-ID')
    company_name = request.headers.get('X-Company-Name')
    if customer_id:
        logger.info("X-Customer-ID: %s", customer_id)
    if company_name:
        logger.info("X-Company-Name: %s", company_name)
    
    # 處理 Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        admin_id = auth_header.split(' ')[1]
        try:
            admin_id = int(admin_id)
            session['admin_id'] = admin_id
            session.modified = True
        except ValueError:
            logger.error("Invalid admin_id format: %s", admin_id)

# 設置響應頭
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    logger.info("请求Origin: '%s'", origin)
    logger.info("允许的Origins: %s", ALLOWED_ORIGINS)
    
    if origin in ALLOWED_ORIGINS:
        response.headers.update({
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Customer-ID, X-Company-Name, X-Requested-With',
            'Access-Control-Allow-Methods': 'GET, PUT, POST, DELETE, OPTIONS',
            'Access-Control-Max-Age': '3600',
            'Vary': 'Origin'
        })
    else:
        logger.warning("Origin不匹配: '%s' 不在允许列表中", origin)
    return response
# 前端靜態文件路由
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static_files(path):
    # 確定前端靜態文件所在的目錄
    static_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'seatic', 'dist')
    
    if path and os.path.exists(os.path.join(static_folder, path)):
        return send_from_directory(static_folder, path)
    else:
        return send_from_directory(static_folder, 'index.html')

# 添加靜態文件路由，用於訪問上傳的文件
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供靜態文件訪問"""
    try:
        logger.info("请求上传文件: %s", filename)
        logger.info("完整路径: %s", os.path.join(UPLOAD_FOLDER, filename))
        
        # 獲取文件的基本名稱(不含路徑)
        basename = os.path.basename(filename)
        
        # 嘗試從資料庫中獲取原始文件名
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 嘗試查找匹配的圖片
            cursor.execute("SELECT image_original_filename FROM products WHERE image_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(UPLOAD_FOLDER, filename)
                # 使用RFC 5987編碼格式
                encoded_filename = urllib.parse.quote(original_filename)
                response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
                logger.info("從資料庫獲取圖片原始文件名: %s", original_filename)
                return response
                
            # 嘗試查找匹配的文件
            cursor.execute("SELECT dm_original_filename FROM products WHERE dm_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(UPLOAD_FOLDER, filename)
                # 使用RFC 5987編碼格式
                encoded_filename = urllib.parse.quote(original_filename)
                response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
                logger.info("從資料庫獲取文件原始文件名: %s", original_filename)
                return response
        
        # 如果資料庫中沒有找到，嘗試從文件名中提取
        original_filename = extract_original_filename(basename)
        
        if original_filename and original_filename != basename:
            response = send_from_directory(UPLOAD_FOLDER, filename)
            # 使用RFC 5987編碼格式
            encoded_filename = urllib.parse.quote(original_filename)
            response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
            logger.info("從文件名提取原始文件名: %s", original_filename)
            return response
            
        # 如果都沒有找到，直接返回文件
        return send_from_directory(UPLOAD_FOLDER, filename)
        
    except Exception as e:
        logger.error("處理文件訪問出錯: %s", str(e))
        return send_from_directory(UPLOAD_FOLDER, filename)

# 註冊藍圖
app.register_blueprint(product_bp, url_prefix='/api')
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(customer_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/api')
app.register_blueprint(order_bp, url_prefix='/api')
app.register_blueprint(line_bot_bp, url_prefix='/api/line')
app.register_blueprint(log_bp, url_prefix='/api/log')
app.register_blueprint(order_check_bp, url_prefix='/api')

# 初始化調度器
scheduler = initialize_scheduler()

# 註冊應用關閉時的清理函數
atexit.register(shutdown_scheduler)

if __name__ == '__main__':
    app.run(debug=True, port=5000)