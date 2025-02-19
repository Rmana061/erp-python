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

app = Flask(__name__)

# Session 配置
app.secret_key = os.getenv('SESSION_SECRET_KEY')
app.config['SESSION_COOKIE_SECURE'] = False  # 在開發環境中關閉 HTTPS 要求
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # 允許跨域請求
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # session 過期時間設為 30 分鐘
app.config['SESSION_COOKIE_DOMAIN'] = None  # 允許所有域名
app.config['SESSION_COOKIE_PATH'] = '/'  # Cookie路徑
app.config['SESSION_COOKIE_NAME'] = os.getenv('SESSION_COOKIE_NAME')

# 在每個請求前檢查 session
@app.before_request
def before_request():
    print("當前 session:", dict(session))
    print(f"請求路徑: {request.path}")
    print(f"請求方法: {request.method}")
    print(f"Cookie: {request.cookies}")
    print(f"Origin: {request.headers.get('Origin')}")

# CORS 配置
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS').split(',')
CORS(app, resources={
    r"/*": {
        "origins": ALLOWED_ORIGINS,
        "supports_credentials": True,
        "allow_headers": ["Content-Type", "Authorization", "Accept", "X-Line-Signature"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "expose_headers": ["Content-Type", "Authorization", "Set-Cookie"],
        "max_age": 600
    }
})

# 设置响应头
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,Accept,X-Line-Signature'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        response.headers['Access-Control-Max-Age'] = '600'
        response.headers['Access-Control-Expose-Headers'] = 'Content-Type,Authorization,Set-Cookie'
        response.headers['Vary'] = 'Origin'
    
    # 處理 OPTIONS 請求
    if request.method == 'OPTIONS':
        return response

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)