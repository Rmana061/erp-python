from flask import Blueprint, request, abort, jsonify, session, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, PostbackTemplateAction,
    URIAction, JoinEvent
)
import os
from dotenv import load_dotenv
from backend.config.database import get_db_connection
from urllib.parse import quote
import requests
from flask_cors import CORS
import psycopg2.extras
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()

# 从环境变量获取配置
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ID = os.getenv('LINE_CHANNEL_ID')
LINE_LIFF_ID = os.getenv('LINE_LIFF_ID')
LINE_LIFF_ENDPOINT = os.getenv('LINE_LIFF_ENDPOINT')
LINE_BOT_BASIC_ID = os.getenv('LINE_BOT_BASIC_ID')

# 允许的来源域名
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS').split(',')

line_bot_bp = Blueprint('line_bot', __name__)
CORS(line_bot_bp, supports_credentials=True, origins=ALLOWED_ORIGINS)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@line_bot_bp.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

@line_bot_bp.route("/generate-bind-url", methods=['POST'])
def generate_bind_url():
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        bind_type = data.get('bind_type', 'user')  # 默认为 'user'
        
        # 打印請求信息以便調試
        logger.debug("Generate bind URL request: customer_id=%s, bind_type=%s", customer_id, bind_type)
        logger.debug("Request headers: %s", dict(request.headers))
        
        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "缺少客戶ID"
            }), 400
            
        # 使用环境变量中的 LIFF ID
        line_login_url = (
            f"https://liff.line.me/{LINE_LIFF_ID}"
            f"?customer_id={quote(str(customer_id))}"
            f"&type={quote(bind_type)}"
        )
        logger.debug("Generated LIFF URL: %s", line_login_url)
        
        return jsonify({
            "status": "success",
            "data": {
                "bind_url": line_login_url,
                "url": line_login_url  # 兼容性保留
            }
        })
        
    except Exception as e:
        logger.error("Error generating bind URL: %s", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@line_bot_bp.route("/callback", methods=['POST'])
def callback():
    # 获取 X-Line-Signature 头部值
    signature = request.headers['X-Line-Signature']

    # 获取请求体内容
    body = request.get_data(as_text=True)

    try:
        # 打印出请求信息，方便调试
        logger.debug("=== LINE Callback ===")
        logger.debug("Headers: %s", dict(request.headers))
        logger.debug("Body: %s", body)
        
        # 验证签名
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("Invalid signature error")
        abort(400)

    return 'OK'

@line_bot_bp.route("/line-binding", methods=['GET', 'POST', 'OPTIONS'])
def line_login_callback():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        data = request.get_json()
        if not data:
            data = request.form
            
        logger.debug("Received callback with data: %s", data)
        logger.debug("Headers: %s", dict(request.headers))
        
        code = data.get('code')
        customer_id = data.get('customer_id')
        error = data.get('error')
        error_description = data.get('error_description')

        if error:
            logger.warning("Authorization error: %s - %s", error, error_description)
            return jsonify({
                "status": "error",
                "message": error_description or "授權失敗"
            }), 400

        if not code:
            logger.warning("Missing code parameter")
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400

        # 使用授權碼獲取訪問令牌
        token_url = "https://api.line.me/oauth2/v2.1/token"
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINE_LIFF_ENDPOINT,
            "client_id": LINE_CHANNEL_ID,
            "client_secret": LINE_CHANNEL_SECRET
        }
        
        logger.debug("Token request data: %s", token_data)
        
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()
        
        logger.debug("Token response: %s", token_json)

        if 'error' in token_json:
            error_msg = f"獲取訪問令牌失敗: {token_json.get('error_description')}"
            logger.error(error_msg)
            return jsonify({
                "status": "error",
                "message": error_msg
            }), 400

        # 使用訪問令牌獲取用戶信息
        profile_url = "https://api.line.me/v2/profile"
        headers = {
            "Authorization": f"Bearer {token_json['access_token']}"
        }
        
        logger.debug("Profile request headers: %s", headers)
        
        profile_response = requests.get(profile_url, headers=headers)
        profile_json = profile_response.json()
        
        logger.debug("Profile response: %s", profile_json)

        if 'error' in profile_json:
            error_msg = f"獲取用戶信息失敗: {profile_json.get('error_description')}"
            logger.error(error_msg)
            return jsonify({
                "status": "error",
                "message": error_msg
            }), 400

        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "缺少客戶ID"
            }), 400

        # 綁定 LINE 帳號
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                
                # 检查该LINE账号是否已经绑定到其他客户
                cursor.execute("""
                    SELECT cu.id, cu.company_name 
                    FROM line_users lu
                    JOIN customers cu ON lu.customer_id = cu.id
                    WHERE lu.line_user_id = %s 
                      AND lu.customer_id != %s
                      AND cu.status = 'active'
                """, (profile_json['userId'], customer_id))
                
                existing = cursor.fetchone()
                if existing:
                    return jsonify({
                        "status": "error",
                        "message": f"此LINE帳號已被其他客戶綁定"
                    }), 400
                
                # 获取客户旧数据用于记录日志
                cursor.execute("""
                    SELECT id, username, company_name, contact_name, phone, email, address,
                           viewable_products, remark, reorder_limit_days, status
                    FROM customers 
                    WHERE id = %s AND status = 'active'
                """, (customer_id,))
                
                old_data_row = cursor.fetchone()
                if not old_data_row:
                    return jsonify({
                        "status": "error",
                        "message": "客戶不存在或狀態不正確"
                    }), 400
                    
                old_customer_data = dict(old_data_row)
                # 轉換contact_name為contact_person以保持一致性
                if 'contact_name' in old_customer_data:
                    old_customer_data['contact_person'] = old_customer_data['contact_name']
                
                # 获取现有的LINE用户列表
                cursor.execute("""
                    SELECT id, line_user_id, user_name
                    FROM line_users
                    WHERE customer_id = %s
                """, (customer_id,))
                old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                old_customer_data['line_users'] = old_line_users
                
                # 获取现有的LINE群组列表
                cursor.execute("""
                    SELECT id, line_group_id, group_name
                    FROM line_groups
                    WHERE customer_id = %s
                """, (customer_id,))
                old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
                old_customer_data['line_groups'] = old_line_groups
                
                # 為向后兼容，添加空的line_account字段
                old_customer_data['line_account'] = ''
                
                # 检查此LINE账号是否已经绑定到当前客户
                cursor.execute("""
                    SELECT id FROM line_users 
                    WHERE line_user_id = %s AND customer_id = %s
                """, (profile_json['userId'], customer_id))
                
                # 如果尚未绑定，则创建新绑定
                if not cursor.fetchone():
                    # 绑定LINE用户
                    cursor.execute("""
                        INSERT INTO line_users (
                            customer_id, line_user_id, user_name, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, NOW(), NOW()
                        )
                    """, (customer_id, profile_json['userId'], profile_json.get('displayName', '')))
                
                conn.commit()
                
                # 获取更新后的LINE用户列表
                cursor.execute("""
                    SELECT id, line_user_id, user_name
                    FROM line_users
                    WHERE customer_id = %s
                """, (customer_id,))
                new_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                
                # 准备新客户数据用于日志记录
                new_customer_data = old_customer_data.copy()
                new_customer_data['line_users'] = new_line_users
                
                # 創建變更詳情
                changes = {}
                changes['line_users'] = {
                    'before': [{'user_name': user.get('user_name', '未知用戶')} for user in old_line_users],
                    'after': [{'user_name': user.get('user_name', '未知用戶')} for user in new_line_users]
                }
                
                # 添加LINE帳號變更記錄
                user_name = profile_json.get('displayName', '未知用戶')
                changes['line_account'] = {
                    'before': '',
                    'after': user_name
                }
                
                # 將變更詳情添加到新數據中
                new_customer_data['line_changes'] = changes
                
                try:
                    # 记录日志
                    from backend.services.log_service_registry import LogServiceRegistry
                    
                    # 初始化日志服务并记录操作
                    log_service = LogServiceRegistry.get_service(conn, 'customers')
                    log_service.log_operation(
                        table_name='customers',
                        operation_type='修改',
                        record_id=customer_id,
                        old_data=old_customer_data,
                        new_data=new_customer_data,
                        performed_by=customer_id,
                        user_type='客戶'
                    )
                except Exception as log_error:
                    # 日志记录失败不影响主要功能
                    logger.error("Error logging LINE bind operation: %s", str(log_error))
                
                return jsonify({
                    "status": "success",
                    "message": "LINE帳號綁定成功"
                })
                
        except Exception as e:
            logger.error("Database error: %s", str(e))
            return jsonify({
                "status": "error",
                "message": f"資料庫錯誤: {str(e)}"
            }), 500

    except Exception as e:
        logger.error("Error in LINE login callback: %s", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@line_bot_bp.route("/bind", methods=['POST', 'OPTIONS'])
def bind():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        line_user_id = data.get('line_user_id')
        
        logger.debug("Received bind request: %s", data)
        logger.debug("Headers: %s", dict(request.headers))
        
        if not customer_id or not line_user_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400
            
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                
                # 检查该LINE账号是否已经绑定到其他客户
                cursor.execute("""
                    SELECT cu.id, cu.company_name 
                    FROM line_users lu
                    JOIN customers cu ON lu.customer_id = cu.id
                    WHERE lu.line_user_id = %s 
                      AND lu.customer_id != %s
                      AND cu.status = 'active'
                """, (line_user_id, customer_id))
                
                existing = cursor.fetchone()
                if existing:
                    return jsonify({
                        "status": "error",
                        "message": f"此LINE帳號已被其他客戶綁定"
                    }), 400
                
                # 获取客户旧数据用于记录日志
                cursor.execute("""
                    SELECT id, username, company_name, contact_name, phone, email, address,
                           viewable_products, remark, reorder_limit_days, status
                    FROM customers 
                    WHERE id = %s AND status = 'active'
                """, (customer_id,))
                
                old_data_row = cursor.fetchone()
                if not old_data_row:
                    return jsonify({
                        "status": "error",
                        "message": "客戶不存在或狀態不正確"
                    }), 400
                    
                old_customer_data = dict(old_data_row)
                # 轉換contact_name為contact_person以保持一致性
                if 'contact_name' in old_customer_data:
                    old_customer_data['contact_person'] = old_customer_data['contact_name']
                
                # 获取现有的LINE用户列表
                cursor.execute("""
                    SELECT id, line_user_id, user_name
                    FROM line_users
                    WHERE customer_id = %s
                """, (customer_id,))
                old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                old_customer_data['line_users'] = old_line_users
                
                # 获取现有的LINE群组列表
                cursor.execute("""
                    SELECT id, line_group_id, group_name
                    FROM line_groups
                    WHERE customer_id = %s
                """, (customer_id,))
                old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
                old_customer_data['line_groups'] = old_line_groups
                
                # 为向后兼容，添加空的line_account字段
                old_customer_data['line_account'] = ''
                
                # 检查用户是否已经绑定到当前客户
                cursor.execute("""
                    SELECT id FROM line_users 
                    WHERE line_user_id = %s AND customer_id = %s
                """, (line_user_id, customer_id))
                
                # 如果此LINE账号尚未绑定到当前客户，则创建新绑定
                if not cursor.fetchone():
                    # 绑定新的LINE用户
                    cursor.execute("""
                        INSERT INTO line_users (
                            customer_id, line_user_id, user_name, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, NOW(), NOW()
                        )
                    """, (customer_id, line_user_id, data.get('user_name', '')))
                
                conn.commit()
                
                # 获取更新后的LINE用户列表
                cursor.execute("""
                    SELECT id, line_user_id, user_name
                    FROM line_users
                    WHERE customer_id = %s
                """, (customer_id,))
                new_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                
                # 准备新客户数据用于日志记录
                new_customer_data = old_customer_data.copy()
                new_customer_data['line_users'] = new_line_users
                
                # 創建變更詳情
                changes = {}
                changes['line_users'] = {
                    'before': [{'user_name': user.get('user_name', '未知用戶')} for user in old_line_users],
                    'after': [{'user_name': user.get('user_name', '未知用戶')} for user in new_line_users]
                }
                
                # 添加LINE帳號變更記錄
                user_name = data.get('user_name', '未知用戶')
                changes['line_account'] = {
                    'before': '',
                    'after': user_name
                }
                
                # 將變更詳情添加到新數據中
                new_customer_data['line_changes'] = changes
                
                try:
                    # 记录日志
                    from backend.services.log_service_registry import LogServiceRegistry
                    
                    # 初始化日誌服務並記錄操作
                    log_service = LogServiceRegistry.get_service(conn, 'customers')
                    log_service.log_operation(
                        table_name='customers',
                        operation_type='修改',
                        record_id=customer_id,
                        old_data=old_customer_data,
                        new_data=new_customer_data,
                        performed_by=customer_id,
                        user_type='客戶'
                    )
                except Exception as log_error:
                    # 日誌記錄失敗不影響主要功能
                    logger.error("Error logging LINE bind operation: %s", str(log_error))
                
                # 发送欢迎消息
                try:
                    line_bot_api.push_message(
                        line_user_id,
                        TextSendMessage(text=f'您好！您的帳號已成功綁定。')
                    )
                except Exception as e:
                    logger.error("Error sending welcome message: %s", str(e))
                
                return jsonify({
                    "status": "success",
                    "message": "LINE帳號綁定成功"
                })
                
        except Exception as e:
            logger.error("Database error: %s", str(e))
            return jsonify({
                "status": "error",
                "message": f"資料庫錯誤: {str(e)}"
            }), 500
            
    except Exception as e:
        logger.error("Error in bind: %s", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@handler.add(JoinEvent)
def handle_join(event):
    """處理機器人被加入群組的事件"""
    try:
        # 獲取群組ID
        group_id = event.source.group_id
        
        # 取得群組資訊
        group_summary = line_bot_api.get_group_summary(group_id)
        group_name = group_summary.group_name if hasattr(group_summary, 'group_name') else '未命名群組'
        
        # 回覆歡迎訊息
        welcome_text = (
            f"感謝將我加入「{group_name}」群組！\n\n"
            "請使用以下指令將此群組與您的帳號綁定：\n"
            "「綁定帳號 公司的帳號名稱」\n\n"
            "例如：綁定帳號 company123\n\n"
            "您也可以隨時輸入「功能」來查看所有可用的功能介紹。"
        )
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=welcome_text)
        )
        
    except Exception as e:
        logger.error("處理加入群組事件時發生錯誤: %s", str(e))
        import traceback
        traceback.print_exc()
        # 發送錯誤訊息
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="加入群組時發生錯誤，請稍後再試或聯絡系統管理員。")
            )
        except:
            pass

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_message = event.message.text
        user_id = event.source.user_id
        
        # 檢查是否為群組訊息
        is_group_message = False
        group_id = None
        
        if hasattr(event.source, 'type') and event.source.type == 'group':
            is_group_message = True
            group_id = event.source.group_id
        
        # 定義訂單相關指令和群組特定指令
        order_commands = ['近兩週訂單', '待確認訂單', '已確認訂單', '已完成訂單']
        group_specific_commands = ['功能', '綁定帳號']
        
        # 檢查消息是否是各類指令
        is_order_command = user_message.strip() in order_commands
        is_bind_command = user_message.startswith('綁定帳號') and len(user_message.split()) >= 2
        is_help_command = user_message.strip() == '功能'
        
        # 決定當前消息是否需要處理
        if is_group_message:
            # 群組消息：只處理訂單指令、綁定指令和功能指令
            should_process = is_order_command or is_bind_command or is_help_command
        else:
            # 私聊消息：只處理訂單指令
            should_process = is_order_command
        
        # 如果不需要處理這個消息，直接退出
        if not should_process:
            return
        
        # 處理"功能"指令 (只在群組中回應)
        if is_group_message and is_help_command:
            feature_text = (
                "📱 功能列表 📱\n\n"
                "🔹 綁定帳號 [公司帳號名稱]\n"
                "   將此LINE群組與您的公司帳號綁定\n"
                "   範例：綁定帳號 company123\n\n"
                "🔹 近兩週訂單\n"
                "   查詢最近14天內的前10筆訂單狀態\n\n"
                "🔹 待確認訂單\n"
                "   查詢尚未確認的前10筆訂單\n\n"
                "🔹 已確認訂單\n"
                "   查詢已確認但尚未出貨的前10筆訂單\n\n"
                "🔹 已完成訂單\n"
                "   查詢已出貨完成的前10筆訂單\n\n"
                "輸入以上關鍵字即可使用對應功能"
            )
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=feature_text)
            )
            return
            
        # 檢查是否為綁定帳號指令 (只在群組中可用)
        if is_group_message and is_bind_command:
            # 提取使用者名稱
            username = user_message.split(None, 1)[1].strip()
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查使用者名稱是否存在
                cursor.execute("""
                    SELECT id, company_name FROM customers 
                    WHERE username = %s AND status = 'active'
                """, (username,))
                
                customer = cursor.fetchone()
                
                if not customer:
                    # 使用者名稱不存在
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"找不到帳號 '{username}'，請確認帳號名稱是否正確。")
                    )
                    return
                
                customer_id, company_name = customer
                
                # 檢查此群組是否已綁定到其他客戶
                cursor.execute("""
                    SELECT c.id, c.company_name 
                    FROM line_groups lg
                    JOIN customers c ON lg.customer_id = c.id
                    WHERE lg.line_group_id = %s 
                      AND lg.customer_id != %s
                      AND c.status = 'active'
                """, (group_id, customer_id))
                
                existing = cursor.fetchone()
                if existing:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"此群組已綁定到 '{existing[1]}' 公司，無法重複綁定。")
                    )
                    return
                
                # 檢查此群組是否已綁定到當前客戶
                cursor.execute("""
                    SELECT id FROM line_groups 
                    WHERE line_group_id = %s AND customer_id = %s
                """, (group_id, customer_id))
                
                # 若尚未綁定，則創建新綁定
                if not cursor.fetchone():
                    # 取得群組名稱
                    try:
                        group_summary = line_bot_api.get_group_summary(group_id)
                        group_name = group_summary.group_name if hasattr(group_summary, 'group_name') else '未命名群組'
                    except:
                        group_name = '未命名群組'
                    
                    # 獲取客戶舊數據用於記錄日誌
                    cursor.execute("""
                        SELECT id, username, company_name, contact_name, phone, email, address,
                               viewable_products, remark, reorder_limit_days, status
                        FROM customers 
                        WHERE id = %s AND status = 'active'
                    """, (customer_id,))
                    
                    old_data_row = cursor.fetchone()
                    old_customer_data = dict(zip([desc[0] for desc in cursor.description], old_data_row))
                    
                    # 獲取現有的LINE用戶列表
                    cursor.execute("""
                        SELECT id, line_user_id, user_name
                        FROM line_users
                        WHERE customer_id = %s
                    """, (customer_id,))
                    old_line_users = [dict(zip(['id', 'line_user_id', 'user_name'], row)) for row in cursor.fetchall()]
                    old_customer_data['line_users'] = old_line_users
                    
                    # 獲取現有的LINE群組列表
                    cursor.execute("""
                        SELECT id, line_group_id, group_name
                        FROM line_groups
                        WHERE customer_id = %s
                    """, (customer_id,))
                    old_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
                    old_customer_data['line_groups'] = old_line_groups
                    
                    # 為向后兼容，添加空的line_account字段
                    old_customer_data['line_account'] = ''
                    
                    # 綁定新的LINE群組
                    cursor.execute("""
                        INSERT INTO line_groups (
                            customer_id, line_group_id, group_name, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, NOW(), NOW()
                        )
                    """, (customer_id, group_id, group_name))
                    
                    conn.commit()
                    
                    # 獲取更新後的LINE群組列表
                    cursor.execute("""
                        SELECT id, line_group_id, group_name
                        FROM line_groups
                        WHERE customer_id = %s
                    """, (customer_id,))
                    new_line_groups = [dict(zip(['id', 'line_group_id', 'group_name'], row)) for row in cursor.fetchall()]
                    
                    # 準備新客戶數據用於日誌記錄
                    new_customer_data = old_customer_data.copy()
                    new_customer_data['line_groups'] = new_line_groups
                    
                    # 創建變更詳情
                    changes = {}
                    changes['line_groups'] = {
                        'before': [{'group_name': group.get('group_name', '未命名群組')} for group in old_line_groups],
                        'after': [{'group_name': group.get('group_name', '未命名群組')} for group in new_line_groups]
                    }
                    
                    # 添加LINE帳號變更記錄
                    changes['line_account'] = {
                        'before': '',
                        'after': group_name
                    }
                    
                    # 將變更詳情添加到新數據中
                    new_customer_data['line_changes'] = changes
                    
                    try:
                        # 記錄日誌
                        from backend.services.log_service_registry import LogServiceRegistry
                        
                        # 初始化日誌服務並記錄操作
                        log_service = LogServiceRegistry.get_service(conn, 'customers')
                        log_service.log_operation(
                            table_name='customers',
                            operation_type='修改',
                            record_id=customer_id,
                            old_data=old_customer_data,
                            new_data=new_customer_data,
                            performed_by=customer_id,
                            user_type='客戶'
                        )
                    except Exception as log_error:
                        # 日誌記錄失敗不影響主要功能
                        logger.error("Error logging LINE group bind operation: %s", str(log_error))
                    
                    # 回覆綁定成功訊息
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"群組已成功綁定到 '{company_name}' 公司！您現在可以在此群組中接收訂單通知。")
                    )
                else:
                    # 已經綁定過了
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"此群組已經綁定到 '{company_name}' 公司。")
                    )
                
                return
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查對應的綁定情況
            if is_group_message:
                # 群組消息：檢查群組綁定
                cursor.execute("""
                    SELECT c.id, c.company_name 
                    FROM customers c
                    JOIN line_groups lg ON c.id = lg.customer_id
                    WHERE lg.line_group_id = %s AND c.status = 'active'
                """, (group_id,))
            else:
                # 私聊消息：檢查用戶綁定
                cursor.execute("""
                    SELECT c.id, c.company_name 
                    FROM customers c
                    JOIN line_users lu ON c.id = lu.customer_id
                    WHERE lu.line_user_id = %s AND c.status = 'active'
                """, (user_id,))
            
            customer = cursor.fetchone()
            
            # 如果未綁定，提示用戶需要綁定
            if not customer:
                if is_group_message:
                    reply_text = "此群組尚未綁定帳號，請先完成帳號綁定。\n\n您可以輸入「功能」查看如何綁定帳號。"
                else:
                    reply_text = "您尚未綁定帳號，請先完成帳號綁定。"
                
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )
                return
            
            # 處理訂單相關指令
            if is_order_command:
                customer_id, company_name = customer
                
                if user_message == '近兩週訂單':
                    cursor.execute("""
                        SELECT DISTINCT o.order_number, o.created_at, 
                               CASE 
                                   WHEN o.order_shipped THEN '已出貨'
                                   WHEN o.order_confirmed THEN '已確認'
                                   ELSE '待確認'
                               END as status,
                               string_agg(
                                   p.name || ' x' || od.product_quantity || od.product_unit || 
                                   ' (' || od.order_status || ')' ||
                                   CASE 
                                       WHEN od.remark IS NOT NULL AND od.remark != '' 
                                       THEN E'\n客戶備註: ' || od.remark
                                       ELSE ''
                                   END ||
                                   CASE 
                                       WHEN od.supplier_note IS NOT NULL AND od.supplier_note != '' 
                                       THEN E'\n供應商備註: ' || od.supplier_note
                                       ELSE ''
                                   END,
                                   E'\n'
                               ) as product_details
                        FROM orders o
                        JOIN order_details od ON o.id = od.order_id
                        JOIN products p ON od.product_id = p.id
                        WHERE o.customer_id = %s 
                        AND o.created_at >= NOW() - INTERVAL '14 days'
                        GROUP BY o.id, o.order_number, o.created_at, o.order_confirmed, o.order_shipped
                        ORDER BY o.created_at DESC
                        LIMIT 10
                    """, (customer_id,))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {company_name}，以下為最新的10筆近兩週訂單：\n\n"
                        for order in orders:
                            reply_text += f"訂單編號：{order[0]}\n"
                            reply_text += f"建立時間：{order[1].strftime('%Y-%m-%d')}\n"
                            reply_text += f"狀態：{order[2]}\n"
                            reply_text += f"訂購商品：\n{order[3]}\n"
                            reply_text += "-------------------\n"
                    else:
                        reply_text = "近兩週內沒有訂單記錄。"

                elif user_message == '待確認訂單':
                    cursor.execute("""
                        SELECT DISTINCT o.order_number, o.created_at,
                               string_agg(
                                   p.name || ' x' || od.product_quantity || od.product_unit || 
                                   ' (' || od.order_status || ')' ||
                                   CASE 
                                       WHEN od.remark IS NOT NULL AND od.remark != '' 
                                       THEN E'\n客戶備註: ' || od.remark
                                       ELSE ''
                                   END ||
                                   CASE 
                                       WHEN od.supplier_note IS NOT NULL AND od.supplier_note != '' 
                                       THEN E'\n供應商備註: ' || od.supplier_note
                                       ELSE ''
                                   END,
                                   E'\n'
                               ) as product_details
                        FROM orders o
                        JOIN order_details od ON o.id = od.order_id
                        JOIN products p ON od.product_id = p.id
                        WHERE o.customer_id = %s 
                        AND NOT o.order_confirmed 
                        AND NOT o.order_shipped
                        GROUP BY o.id, o.order_number, o.created_at
                        ORDER BY o.created_at DESC
                        LIMIT 10
                    """, (customer_id,))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {company_name}，以下為最新的10筆待確認訂單：\n\n"
                        for order in orders:
                            reply_text += f"訂單編號：{order[0]}\n"
                            reply_text += f"建立時間：{order[1].strftime('%Y-%m-%d')}\n"
                            reply_text += f"訂購商品：\n{order[2]}\n"
                            reply_text += "-------------------\n"
                    else:
                        reply_text = "目前沒有待確認的訂單。"

                elif user_message == '已確認訂單':
                    cursor.execute("""
                        SELECT DISTINCT o.order_number, o.created_at,
                               string_agg(
                                   p.name || ' x' || od.product_quantity || od.product_unit || 
                                   ' (' || od.order_status || ')' ||
                                   CASE 
                                       WHEN od.remark IS NOT NULL AND od.remark != '' 
                                       THEN E'\n客戶備註: ' || od.remark
                                       ELSE ''
                                   END ||
                                   CASE 
                                       WHEN od.supplier_note IS NOT NULL AND od.supplier_note != '' 
                                       THEN E'\n供應商備註: ' || od.supplier_note
                                       ELSE ''
                                   END,
                                   E'\n'
                               ) as product_details
                        FROM orders o
                        JOIN order_details od ON o.id = od.order_id
                        JOIN products p ON od.product_id = p.id
                        WHERE o.customer_id = %s 
                        AND o.order_confirmed 
                        AND NOT o.order_shipped
                        GROUP BY o.id, o.order_number, o.created_at
                        ORDER BY o.created_at DESC
                        LIMIT 10
                    """, (customer_id,))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {company_name}，以下為最新的10筆已確認訂單：\n\n"
                        for order in orders:
                            reply_text += f"訂單編號：{order[0]}\n"
                            reply_text += f"建立時間：{order[1].strftime('%Y-%m-%d')}\n"
                            reply_text += f"訂購商品：\n{order[2]}\n"
                            reply_text += "-------------------\n"
                    else:
                        reply_text = "目前沒有已確認的訂單。"

                elif user_message == '已完成訂單':
                    cursor.execute("""
                        SELECT DISTINCT o.order_number, o.created_at,
                               string_agg(
                                   p.name || ' x' || od.product_quantity || od.product_unit || 
                                   ' (' || od.order_status || ')' ||
                                   CASE 
                                       WHEN od.remark IS NOT NULL AND od.remark != '' 
                                       THEN E'\n客戶備註: ' || od.remark
                                       ELSE ''
                                   END ||
                                   CASE 
                                       WHEN od.supplier_note IS NOT NULL AND od.supplier_note != '' 
                                       THEN E'\n供應商備註: ' || od.supplier_note
                                       ELSE ''
                                   END,
                                   E'\n'
                               ) as product_details
                        FROM orders o
                        JOIN order_details od ON o.id = od.order_id
                        JOIN products p ON od.product_id = p.id
                        WHERE o.customer_id = %s 
                        AND o.order_shipped
                        GROUP BY o.id, o.order_number, o.created_at
                        ORDER BY o.created_at DESC
                        LIMIT 10
                    """, (customer_id,))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {company_name}，以下為最新的10筆已完成訂單：\n\n"
                        for order in orders:
                            reply_text += f"訂單編號：{order[0]}\n"
                            reply_text += f"建立時間：{order[1].strftime('%Y-%m-%d')}\n"
                            reply_text += f"訂購商品：\n{order[2]}\n"
                            reply_text += "-------------------\n"
                    else:
                        reply_text = "目前沒有已完成的訂單。"
                
                # 回覆訂單查詢結果
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )
            
    except Exception as e:
        logger.error("Error handling message: %s", str(e))
        # 只在特定命令出錯時才發送錯誤訊息
        order_commands = ['近兩週訂單', '待確認訂單', '已確認訂單', '已完成訂單']
        if (user_message.strip() in order_commands) or (is_group_message and (user_message.strip() == '功能' or user_message.startswith('綁定帳號'))):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="抱歉，系統發生錯誤，請稍後再試。")
            ) 