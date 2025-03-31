import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from dotenv import load_dotenv
import sys
import traceback
import base64
import re
import logging

# 加載環境變數
load_dotenv()

# 獲取 logger
logger = logging.getLogger(__name__)

class EmailSender:
    def __init__(self):
        # 默認郵件賬號
        self.sender_email = os.getenv('GMAIL_USER', 'grandholyorder@gmail.com')
        self.sender_name = os.getenv('EMAIL_SENDER_NAME', '訂單系統')
        
        # 郵件功能選項
        self.force_enabled = False  # 如果需要跳過密碼檢查，設置為True
        self.dummy_mode = False  # 如果設置為True，只會模擬發送郵件而不實際發送
        
        # 從環境變量讀取密碼
        env_password = os.getenv('GMAIL_APP_PASSWORD', '')
        
        if env_password:
            # 如果發現包含非ASCII字符，嘗試清理它們
            try:
                env_password.encode('ascii')
            except UnicodeEncodeError:
                # 只保留ASCII字符
                env_password = ''.join(c for c in env_password if ord(c) < 128)
        
        # 清理密碼：去除空格等
        self.raw_password = env_password
        self.sender_password = self._clean_password(self.raw_password)
        
        # 設置SMTP服務器信息
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        
        # 調試模式
        self.debug_mode = os.getenv('EMAIL_DEBUG', 'false').lower() == 'true'
        
        # 是否啟用郵件功能標誌
        self.email_enabled = bool(self.sender_password) or self.force_enabled
        
        # 如果啟用了模擬模式，停用實際發送
        if self.dummy_mode:
            logger.info("📢 郵件模擬模式已啟用，系統將模擬發送郵件但不會實際發送")
            self.email_enabled = False
            
        if not self.email_enabled:
            logger.warning("⚠️ 警告：未設置有效的郵件密碼，郵件功能已禁用。訂單操作將繼續，但不會發送郵件通知。")
        else:
            logger.info("郵件功能已啟用，使用賬號: %s", self.sender_email)

    def _clean_password(self, password):
        """清理密碼，確保它只包含有效字符"""
        if not password:
            return ''
            
        # 移除所有空格 - Google應用密碼不需要空格
        cleaned = password.replace(' ', '')
        
        # 確保密碼只包含字母和數字
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', cleaned)
        
        return cleaned

    def _send_email(self, recipient_email, subject, title, content_data, is_order_items=True, show_notes=False, show_status=False):
        # 模擬模式檢查
        if self.dummy_mode:
            logger.info("📧 [模擬模式] 模擬發送郵件到: %s，主題: %s", recipient_email, subject)
            return True, "郵件模擬模式已啟用，不會實際發送郵件"
            
        # 如果郵件功能被禁用，記錄日誌並返回
        if not self.email_enabled:
            logger.info("📧 模擬發送郵件到: %s，主題: %s", recipient_email, subject)
            return True, "郵件功能已禁用，但系統將繼續運行"
            
        try:
            logger.info("準備發送郵件到: %s", recipient_email)
            logger.debug("使用郵件帳號: %s", self.sender_email)
            
            # 構建郵件
            message = MIMEMultipart()
            message['From'] = self.sender_email
            message['To'] = recipient_email
            message['Subject'] = Header(subject, 'utf-8').encode()

            # 構建郵件內容
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2 style="color: {'#4CAF50' if '下單' in subject or '確認' in subject or '出貨' in subject else '#dc3545'}">{title}</h2>
                <p>您的訂單{
                    '已成功送出' if '下單' in subject 
                    else '已審核確認' if '確認' in subject 
                    else '已駁回' if '駁回' in subject
                    else '已出貨' if '出貨' in subject
                    else '自行取消'
                }：</p>
                <ul style="list-style-type: none; padding-left: 0;">
                    <li><strong>訂單編號：</strong>{content_data.get('order_number', '')}</li>
                    <li><strong>{
                        '下單' if '下單' in subject 
                        else '確認' if '確認' in subject 
                        else '駁回' if '駁回' in subject
                        else '出貨' if '出貨' in subject
                        else '取消'
                    }日期：</strong>{content_data.get('order_date' if '下單' in subject else 'cancel_date' if '取消' in subject else 'confirm_date', '')}</li>
                </ul>
            """

            if is_order_items:
                html_content += f"""
                <h3 style="color: #2196F3;">{'訂購' if '下單' in subject or '確認' in subject else '駁回' if '駁回' in subject else '已出貨' if '出貨' in subject else '取消的'}商品：</h3>
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                    <tr style="background-color: #f5f5f5;">
                        <th style="padding: 10px; border: 1px solid #ddd;">商品名稱</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">數量</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">單位</th>
                        {'<th style="padding: 10px; border: 1px solid #ddd;">預計出貨日期</th>' if '下單' in subject or '確認' in subject else ''}
                        {'''<th style="padding: 10px; border: 1px solid #ddd;">備註</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">供應商備註</th>''' if show_notes else ''}
                        {'<th style="padding: 10px; border: 1px solid #ddd;">產品狀態</th>' if show_status else ''}
                    </tr>
                """

                for item in content_data.get('items', []):
                    remark = item.get('remark', '')
                    supplier_note = item.get('supplier_note', '')
                    
                    # 獲取產品狀態 - 檢查多個可能的字段名稱
                    product_status = None
                    for status_field in ['status', 'product_status', 'order_status', '狀態']:
                        if status_field in item and item[status_field]:
                            product_status = item[status_field]
                            break
                    
                    # 如果沒有找到狀態，則嘗試從操作系統字段中推斷
                    if not product_status:
                        if '已取消' in str(item) or '取消' in str(item):
                            product_status = '已取消'
                        elif '已駁回' in str(item) or '駁回' in str(item):
                            product_status = '已駁回'
                        elif '已出貨' in str(item) or '出貨' in str(item):
                            product_status = '已出貨'
                        elif '待確認' in str(item):
                            product_status = '待確認'
                        elif '已確認' in str(item) or '確認' in str(item):
                            product_status = '已確認'
                        elif 'shipping_date' in item and item['shipping_date']:
                            # 如果有出貨日期，可能是已出貨狀態
                            product_status = '已出貨'
                        else:
                            # 根據郵件類型設置適當的默認狀態
                            if '出貨' in subject:
                                product_status = '已出貨'
                            else:
                                product_status = '已確認'
                    
                    # 設置產品狀態的顯示顏色
                    status_color = '#4CAF50'  # 綠色為默認（正常）
                    if product_status:
                        if '取消' in product_status or '駁回' in product_status:
                            status_color = '#dc3545'  # 紅色
                        elif '待確認' in product_status or '待處理' in product_status:
                            status_color = '#ff9800'  # 橙色
                        elif '已出貨' in product_status:
                            status_color = '#2196F3'  # 藍色
                    
                    html_content += f"""
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('product_name', '')}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('quantity', '')}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('unit', '')}</td>
                            {'<td style="padding: 10px; border: 1px solid #ddd;">{}</td>'.format(item.get('shipping_date') if item.get('shipping_date') else '待和供應商確認') if '下單' in subject or '確認' in subject else ''}
                            {f'''<td style="padding: 10px; border: 1px solid #ddd;">{remark if remark else ''}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{supplier_note if supplier_note else ''}</td>''' if show_notes else ''}
                            {f'''<td style="padding: 10px; border: 1px solid #ddd; color: {status_color};">{product_status}</td>''' if show_status else ''}
                        </tr>
                    """

                html_content += """
                    </table>
                """

            html_content += """
                <p style="margin-top: 20px; color: #666;">如有任何問題，請聯繫我們的客服人員。</p>
                <p style="color: #999; font-size: 12px;">此郵件為系統自動發送，請勿直接回覆。</p>
            </body>
            </html>
            """

            # 使用UTF-8編碼附加郵件內容
            part = MIMEText(html_content, 'html', 'utf-8')
            message.attach(part)

            try:
                # 發送郵件
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    # 如果啟用了調試模式，顯示更多SMTP對話信息
                    if self.debug_mode:
                        server.set_debuglevel(1)
                        
                    server.starttls()
                    logger.info("開始 SMTP 登入...")
                    
                    try:
                        server.login(self.sender_email, self.sender_password)
                    except UnicodeEncodeError as ue:
                        logger.error("密碼包含非ASCII字符，無法用於SMTP登入: %s", str(ue))
                        raise ValueError("郵件密碼包含非ASCII字符，請檢查您的應用程式密碼設置")
                    except smtplib.SMTPAuthenticationError as auth_error:
                        logger.error("SMTP認證失敗: %s", str(auth_error))
                        
                        # 提供故障排除指南
                        logger.info("\n可能的原因和解決方案：")
                        logger.info("1. 密碼錯誤 - 請確認您的應用密碼是否正確")
                        logger.info("2. 需要啟用兩步驗證 - 訪問 https://myaccount.google.com/security")
                        logger.info("3. 請確認.env文件中的格式正確，沒有多餘的引號或特殊字符")
                        
                        raise
                    except Exception as auth_error:
                        logger.error("SMTP登入時發生未知錯誤: %s", str(auth_error))
                        raise
                    
                    logger.info("SMTP 登入成功")
                    
                    # 發送郵件
                    mail_string = message.as_string()
                    server.sendmail(self.sender_email, recipient_email, mail_string)
                    logger.info("郵件發送成功")
                
                return True, "郵件發送成功"
            except Exception as smtp_error:
                logger.error("SMTP發送錯誤: %s", str(smtp_error))
                logger.error("錯誤詳情:")
                traceback.print_exc()
                logger.warning("⚠️ 郵件發送失敗，但系統將繼續運行")
                return False, str(smtp_error)

        except Exception as e:
            logger.error("發送郵件時出錯: %s", str(e))
            logger.error("錯誤詳情:")
            traceback.print_exc()
            logger.warning("⚠️ 郵件發送失敗，但系統將繼續運行")
            return False, str(e)

    def send_order_confirmation(self, recipient_email, order_data):
        """發送訂單確認郵件"""
        subject = f"訂單確認通知 - {order_data.get('order_number', '')}"
        title = "訂單確認通知"
        return self._send_email(recipient_email, subject, title, order_data, show_notes=True, show_status=True)

    def send_order_cancellation(self, recipient_email, order_data):
        """發送訂單取消郵件"""
        subject = f"訂單取消通知 - {order_data.get('order_number', '')}"
        title = "訂單取消通知"
        return self._send_email(recipient_email, subject, title, order_data, show_notes=True, show_status=True)

    def send_order_approved(self, recipient_email, order_data):
        """發送訂單審核通過郵件"""
        subject = f"訂單審核通過通知 - {order_data.get('order_number', '')}"
        title = "訂單審核通過通知"
        return self._send_email(recipient_email, subject, title, order_data, show_notes=True, show_status=True)

    def send_order_rejected(self, recipient_email, order_data):
        """發送訂單駁回郵件"""
        subject = f"訂單駁回通知 - {order_data.get('order_number', '')}"
        title = "訂單駁回通知"
        return self._send_email(recipient_email, subject, title, order_data, show_notes=True, show_status=True)

    def send_order_shipped(self, recipient_email, order_data):
        """發送訂單出貨郵件"""
        subject = f"訂單出貨通知 - {order_data.get('order_number', '')}"
        title = "訂單出貨通知"
        return self._send_email(recipient_email, subject, title, order_data, show_notes=True, show_status=True) 