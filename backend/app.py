import os
import sys
from dotenv import load_dotenv
import base64
import urllib.parse

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

# 定义从双轨文件名中提取原始文件名的函数
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

app = Flask(__name__)

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

    print("當前 session:", dict(session))
    print(f"請求路徑: {request.path}")
    print(f"請求方法: {request.method}")
    print(f"Cookie: {request.cookies}")
    print(f"Origin: {request.headers.get('Origin')}")
    print(f"Authorization: {request.headers.get('Authorization')}")
    
    # 打印前端传递的自定义头部
    customer_id = request.headers.get('X-Customer-ID')
    company_name = request.headers.get('X-Company-Name')
    if customer_id:
        print(f"X-Customer-ID: {customer_id}")
    if company_name:
        print(f"X-Company-Name: {company_name}")
    
    # 處理 Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        admin_id = auth_header.split(' ')[1]
        try:
            admin_id = int(admin_id)
            session['admin_id'] = admin_id
            session.modified = True
        except ValueError:
            print(f"Invalid admin_id format: {admin_id}")

# 设置响应头
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    print(f"请求Origin: '{origin}'")
    print(f"允许的Origins: {ALLOWED_ORIGINS}")
    
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
        print(f"Origin不匹配: '{origin}' 不在允许列表中")
    return response

# 添加静态文件路由，用于访问上传的文件
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供静态文件访问"""
    try:
        print(f"请求上传文件: {filename}")
        print(f"完整路径: {os.path.join(UPLOAD_FOLDER, filename)}")
        
        # 获取文件的基本名称(不含路径)
        basename = os.path.basename(filename)
        
        # 尝试从数据库中获取原始文件名
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 尝试查找匹配的图片
            cursor.execute("SELECT image_original_filename FROM products WHERE image_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(UPLOAD_FOLDER, filename)
                # 使用RFC 5987编码格式
                encoded_filename = urllib.parse.quote(original_filename)
                response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
                print(f"从数据库获取图片原始文件名: {original_filename}")
                return response
                
            # 尝试查找匹配的文档
            cursor.execute("SELECT dm_original_filename FROM products WHERE dm_url LIKE %s", (f'%{basename}%',))
            result = cursor.fetchone()
            
            if result and result[0]:
                original_filename = result[0]
                response = send_from_directory(UPLOAD_FOLDER, filename)
                # 使用RFC 5987编码格式
                encoded_filename = urllib.parse.quote(original_filename)
                response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
                print(f"从数据库获取文档原始文件名: {original_filename}")
                return response
        
        # 如果数据库中没有找到，尝试从文件名中提取
        original_filename = extract_original_filename(basename)
        
        if original_filename and original_filename != basename:
            response = send_from_directory(UPLOAD_FOLDER, filename)
            # 使用RFC 5987编码格式
            encoded_filename = urllib.parse.quote(original_filename)
            response.headers["Content-Disposition"] = f"inline; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
            print(f"从文件名提取原始文件名: {original_filename}")
            return response
            
        # 如果都没有找到，直接返回文件
        return send_from_directory(UPLOAD_FOLDER, filename)
        
    except Exception as e:
        print(f"处理文件访问出错: {str(e)}")
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)