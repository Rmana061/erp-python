from flask import Blueprint, request, abort, jsonify, session, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    TemplateSendMessage, ButtonsTemplate, PostbackTemplateAction,
    URIAction
)
from backend.config.config import LINE_CONFIG
from backend.config.database import get_db_connection
from urllib.parse import quote
import requests
from flask_cors import CORS

line_bot_bp = Blueprint('line_bot', __name__)
CORS(line_bot_bp)

line_bot_api = LineBotApi(LINE_CONFIG['CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(LINE_CONFIG['CHANNEL_SECRET'])


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
            
        # 使用 LIFF URL，确保 customer_id 正确传递
        line_login_url = (
            f"https://liff.line.me/{LINE_CONFIG['LIFF_ID']}"
            f"?customer_id={customer_id}"
        )
        print(f"Generated LIFF URL: {line_login_url}")  # 添加调试日志
        
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

@line_bot_bp.route("/line-binding", methods=['GET'])
def line_login_callback():
    try:
        # 获取授权码和状态
        code = request.args.get('code')
        state = request.args.get('state')  # state 中包含了 customer_id
        error = request.args.get('error')
        error_description = request.args.get('error_description')

        if error:
            return jsonify({
                "status": "error",
                "message": error_description or "授權失敗"
            }), 400

        if not code or not state:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400

        # 使用授权码获取访问令牌
        token_url = "https://api.line.me/oauth2/v2.1/token"
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINE_CONFIG['LIFF_ENDPOINT'],
            "client_id": LINE_CONFIG['CHANNEL_ID'],
            "client_secret": LINE_CONFIG['CHANNEL_SECRET']
        }
        token_response = requests.post(token_url, data=token_data)
        token_json = token_response.json()

        if 'error' in token_json:
            raise Exception(f"獲取訪問令牌失敗: {token_json.get('error_description')}")

        # 使用访问令牌获取用户信息
        profile_url = "https://api.line.me/v2/profile"
        headers = {
            "Authorization": f"Bearer {token_json['access_token']}"
        }
        profile_response = requests.get(profile_url, headers=headers)
        profile_json = profile_response.json()

        if 'error' in profile_json:
            raise Exception(f"獲取用戶信息失敗: {profile_json.get('error_description')}")

        # 绑定 LINE 账号
        bind_response = bind_line_account(state, profile_json['userId'])
        
        if bind_response.status_code != 200:
            raise Exception(f"綁定失敗: {bind_response.json().get('message')}")

        # 重定向到前端绑定成功页面
        return redirect(f"{LINE_CONFIG['FRONTEND_URL']}/account-settings")

    except Exception as e:
        print(f"Error in LINE login callback: {str(e)}")
        error_message = str(e)
        return redirect(f"{LINE_CONFIG['FRONTEND_URL']}/account-settings?error={quote(error_message)}")

@line_bot_bp.route("/bind", methods=['POST', 'OPTIONS'])
def bind():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        data = request.get_json()
        customer_id = data.get('customer_id')
        line_user_id = data.get('line_user_id')
        
        if not customer_id or not line_user_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要參數"
            }), 400
            
        return bind_line_account(customer_id, line_user_id)
        
    except Exception as e:
        print(f"Error in bind: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def bind_line_account(customer_id, line_user_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查是否已經綁定到其他帳號（排除當前客戶）
            cursor.execute("""
                SELECT id, company_name FROM customers 
                WHERE line_account = %s AND id != %s AND status = 'active'
            """, (line_user_id, customer_id))
            
            existing_binding = cursor.fetchone()
            if existing_binding:
                raise Exception(f"此LINE帳號已被其他客戶 {existing_binding[1]} 綁定")
            
            # 更新客戶的LINE帳號
            cursor.execute("""
                UPDATE customers 
                SET line_account = %s,
                    updated_at = NOW()
                WHERE id = %s AND status = 'active'
                RETURNING id, company_name
            """, (line_user_id, customer_id))
            
            result = cursor.fetchone()
            if not result:
                raise Exception("找不到客戶資料或客戶狀態不正確")
                
            conn.commit()
            
            # 發送歡迎訊息
            try:
                # 發送歡迎訊息
                line_bot_api.push_message(
                    line_user_id,
                    TextSendMessage(text=f'{result[1]} 您好！\n您的帳號已成功綁定。')
                )
            except Exception as e:
                print(f"Error sending welcome message: {str(e)}")
            
            return jsonify({
                "status": "success",
                "message": "LINE帳號綁定成功"
            })
            
    except Exception as e:
        raise Exception(f"綁定失敗: {str(e)}")

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