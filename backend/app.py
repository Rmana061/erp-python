import os
import sys
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 將專案根目錄添加到 Python 路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, session, send_from_directory
from flask_cors import CORS
from backend.routes.product_routes import product_bp
from backend.routes.auth_routes import auth_bp
from backend.routes.customer_routes import customer_bp
from backend.routes.admin_routes import admin_bp
from backend.routes.order_routes import order_bp
from backend.routes.line_bot_routes import line_bot_bp
from backend.routes.log_routes import log_bp

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
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS').split(',')
CORS(app, 
     supports_credentials=True,
     origins=ALLOWED_ORIGINS,
     allow_headers=['Content-Type', 'Authorization'],
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
    if origin in ALLOWED_ORIGINS:
        response.headers.update({
            'Access-Control-Allow-Origin': origin,
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Allow-Methods': 'GET, PUT, POST, DELETE, OPTIONS',
            'Access-Control-Max-Age': '3600',
            'Vary': 'Origin'
        })
    return response

# 添加靜態文件處理路由
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    return send_from_directory(uploads_dir, filename)

# 註冊藍圖
app.register_blueprint(product_bp, url_prefix='/api')
app.register_blueprint(auth_bp, url_prefix='/api')
app.register_blueprint(customer_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/api')
app.register_blueprint(order_bp, url_prefix='/api')
app.register_blueprint(line_bot_bp, url_prefix='/api/line')
app.register_blueprint(log_bp, url_prefix='/api/log')

if __name__ == '__main__':
    app.run(debug=True, port=5000)