import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from dotenv import load_dotenv

# 加載環境變數
load_dotenv()

class EmailSender:
    def __init__(self):
        self.sender_email = os.getenv('GMAIL_USER', 'grandholyorder@gmail.com')
        self.sender_password = os.getenv('GMAIL_APP_PASSWORD', '')  # 使用應用程式密碼
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587

    def send_order_confirmation(self, recipient_email, order_data):
        try:
            print(f"準備發送郵件到: {recipient_email}")
            print(f"使用郵件帳號: {self.sender_email}")
            
            # 創建郵件內容
            message = MIMEMultipart()
            message['From'] = str(Header(self.sender_email, 'utf-8'))
            message['To'] = str(Header(recipient_email, 'utf-8'))
            message['Subject'] = str(Header('訂單確認通知', 'utf-8'))

            # 構建郵件內容
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <h2 style="color: #4CAF50;">訂單確認通知</h2>
                <p>您的訂單已成功提交：</p>
                <ul style="list-style-type: none; padding-left: 0;">
                    <li><strong>訂單編號：</strong>{order_data.get('order_number', '')}</li>
                    <li><strong>訂購日期：</strong>{order_data.get('order_date', '')}</li>
                </ul>
                <h3 style="color: #2196F3;">訂購商品：</h3>
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                    <tr style="background-color: #f5f5f5;">
                        <th style="padding: 10px; border: 1px solid #ddd;">商品名稱</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">數量</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">單位</th>
                        <th style="padding: 10px; border: 1px solid #ddd;">預計出貨日期</th>
                    </tr>
            """

            # 添加訂單項目
            for item in order_data.get('items', []):
                html_content += f"""
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;">{item.get('product_name', '')}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{item.get('quantity', '')}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{item.get('unit', '')}</td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{item.get('shipping_date', '')}</td>
                    </tr>
                """

            html_content += """
                </table>
                <p style="margin-top: 20px; color: #666;">如有任何問題，請聯繫我們的客服人員。</p>
                <p style="color: #999; font-size: 12px;">此郵件為系統自動發送，請勿直接回覆。</p>
            </body>
            </html>
            """

            message.attach(MIMEText(html_content, 'html', 'utf-8'))

            # 連接 SMTP 服務器並發送郵件
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                print("開始 SMTP 登入...")
                server.login(self.sender_email, self.sender_password)
                print("SMTP 登入成功")
                server.send_message(message)
                print("郵件發送成功")

            return True, "郵件發送成功"

        except Exception as e:
            print(f"發送郵件時出錯: {str(e)}")
            return False, str(e) 