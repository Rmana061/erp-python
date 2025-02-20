from flask import Blueprint, request, abort, jsonify, session, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, PostbackTemplateAction,
    URIAction
)
import os
from dotenv import load_dotenv
from backend.config.database import get_db_connection
from urllib.parse import quote
import requests
from flask_cors import CORS

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
        
        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "缺少客戶ID"
            }), 400
            
        # 使用环境变量中的 LIFF ID
        line_login_url = (
            f"https://liff.line.me/{LINE_LIFF_ID}"
            f"?customer_id={quote(str(customer_id))}"
        )
        print(f"Generated LIFF URL: {line_login_url}")
        
        return jsonify({
            "status": "success",
            "data": {
                "url": line_login_url
            }
        })
        
    except Exception as e:
        print(f"Error generating bind URL: {str(e)}")
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
        # 验证签名
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@line_bot_bp.route("/line-binding", methods=['POST', 'OPTIONS'])
def line_login_callback():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        data = request.get_json()
        if not data:
            data = request.form
            
        print("Received callback with data:", data)
        print("Headers:", dict(request.headers))
        
        code = data.get('code')
        customer_id = data.get('customer_id')
        error = data.get('error')
        error_description = data.get('error_description')

        if error:
            print(f"Authorization error: {error} - {error_description}")
            return jsonify({
                "status": "error",
                "message": error_description or "授權失敗"
            }), 400

        if not code:
            print("Missing code parameter")
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
        
        print("Token request data:", token_data)
        
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()
        
        print("Token response:", token_json)

        if 'error' in token_json:
            error_msg = f"獲取訪問令牌失敗: {token_json.get('error_description')}"
            print(error_msg)
            return jsonify({
                "status": "error",
                "message": error_msg
            }), 400

        # 使用訪問令牌獲取用戶信息
        profile_url = "https://api.line.me/v2/profile"
        headers = {
            "Authorization": f"Bearer {token_json['access_token']}"
        }
        
        print("Profile request headers:", headers)
        
        profile_response = requests.get(profile_url, headers=headers)
        profile_json = profile_response.json()
        
        print("Profile response:", profile_json)

        if 'error' in profile_json:
            error_msg = f"獲取用戶信息失敗: {profile_json.get('error_description')}"
            print(error_msg)
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
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE customers 
                    SET line_account = %s,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'active'
                    RETURNING id
                """, (profile_json['userId'], customer_id))
                
                result = cursor.fetchone()
                if not result:
                    return jsonify({
                        "status": "error",
                        "message": "客戶不存在或狀態不正確"
                    }), 400
                    
                conn.commit()
                
                return jsonify({
                    "status": "success",
                    "message": "LINE帳號綁定成功"
                })
                
        except Exception as e:
            print(f"Database error: {str(e)}")
            return jsonify({
                "status": "error",
                "message": f"資料庫錯誤: {str(e)}"
            }), 500

    except Exception as e:
        print(f"Error in LINE login callback: {str(e)}")
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
        
        print("Received bind request:", data)
        print("Headers:", dict(request.headers))
        
        if not customer_id or not line_user_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400
            
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 检查是否已经绑定
                cursor.execute("""
                    SELECT id, company_name FROM customers 
                    WHERE line_account = %s AND id != %s AND status = 'active'
                """, (line_user_id, customer_id))
                
                existing = cursor.fetchone()
                if existing:
                    return jsonify({
                        "status": "error",
                        "message": f"此LINE帳號已被其他客戶綁定"
                    }), 400
                
                # 更新绑定
                cursor.execute("""
                    UPDATE customers 
                    SET line_account = %s,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'active'
                    RETURNING id, company_name
                """, (line_user_id, customer_id))
                
                result = cursor.fetchone()
                if not result:
                    return jsonify({
                        "status": "error",
                        "message": "客戶不存在或狀態不正確"
                    }), 400
                    
                conn.commit()
                
                # 发送欢迎消息
                try:
                    line_bot_api.push_message(
                        line_user_id,
                        TextSendMessage(text=f'您好！您的帳號已成功綁定。')
                    )
                except Exception as e:
                    print(f"Error sending welcome message: {str(e)}")
                
                return jsonify({
                    "status": "success",
                    "message": "LINE帳號綁定成功"
                })
                
        except Exception as e:
            print(f"Database error: {str(e)}")
            return jsonify({
                "status": "error",
                "message": f"資料庫錯誤: {str(e)}"
            }), 500
            
    except Exception as e:
        print(f"Error in bind: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_message = event.message.text
        user_id = event.source.user_id
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查用戶是否已綁定
            cursor.execute("""
                SELECT id, company_name FROM customers 
                WHERE line_account = %s AND status = 'active'
            """, (user_id,))
            
            customer = cursor.fetchone()
            
            if customer:
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
                    """, (customer[0],))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {customer[1]}，以下為最新的10筆近兩週訂單：\n\n"
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
                    """, (customer[0],))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {customer[1]}，以下為最新的10筆待確認訂單：\n\n"
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
                    """, (customer[0],))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {customer[1]}，以下為最新的10筆已確認訂單：\n\n"
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
                    """, (customer[0],))
                    
                    orders = cursor.fetchall()
                    if orders:
                        reply_text = f"您好 {customer[1]}，以下為最新的10筆已完成訂單：\n\n"
                        for order in orders:
                            reply_text += f"訂單編號：{order[0]}\n"
                            reply_text += f"建立時間：{order[1].strftime('%Y-%m-%d')}\n"
                            reply_text += f"訂購商品：\n{order[2]}\n"
                            reply_text += "-------------------\n"
                    else:
                        reply_text = "目前沒有已完成的訂單。"
                else:
                    reply_text = f"您好 {customer[1]}，請選擇您要查詢的訂單類型。"
            else:
                reply_text = "您尚未綁定帳號，請先完成帳號綁定。"
                
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            
    except Exception as e:
        print(f"Error handling message: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="抱歉，系統發生錯誤，請稍後再試。")
        ) 