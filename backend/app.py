import os
import sys

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
app.secret_key = 'your-super-secret-key-here'  # 使用固定的密钥
app.config['SESSION_COOKIE_SECURE'] = True  # 暂时关闭 HTTPS 要求
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # 修改为 Lax
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # session 过期时间设为 30 分钟
app.config['SESSION_COOKIE_DOMAIN'] = None  # 允许所有域名
app.config['SESSION_COOKIE_PATH'] = '/'  # Cookie路径

# CORS 配置
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:5173",
            "https://6c2e-111-249-201-216.ngrok-free.app",
            "https://6e12-111-249-201-216.ngrok-free.app"
        ],
        "supports_credentials": True,
        "allow_headers": ["Content-Type", "Authorization", "Accept", "X-Line-Signature"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "expose_headers": ["Content-Type", "Authorization"],
        "max_age": 600
    }
})

# 设置响应头
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    allowed_origins = [
        "http://localhost:5173",
        "https://6c2e-111-249-201-216.ngrok-free.app",
        "https://6e12-111-249-201-216.ngrok-free.app"
    ]
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,Accept,X-Line-Signature'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        response.headers['Access-Control-Max-Age'] = '600'
        response.headers['Access-Control-Expose-Headers'] = 'Content-Type,Authorization'
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