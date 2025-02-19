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

    def _send_email(self, recipient_email, subject, title, content_data, is_order_items=True, show_notes=False):
        try:
            print(f"準備發送郵件到: {recipient_email}")
            print(f"使用郵件帳號: {self.sender_email}")
            
            message = MIMEMultipart()
            message['From'] = str(Header(self.sender_email, 'utf-8'))
            message['To'] = str(Header(recipient_email, 'utf-8'))
            message['Subject'] = str(Header(subject, 'utf-8'))

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
                    </tr>
                """

                for item in content_data.get('items', []):
                    remark = item.get('remark', '')
                    supplier_note = item.get('supplier_note', '')
                    
                    html_content += f"""
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('product_name', '')}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('quantity', '')}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{item.get('unit', '')}</td>
                            {'<td style="padding: 10px; border: 1px solid #ddd;">{}</td>'.format(item.get('shipping_date', '')) if '下單' in subject or '確認' in subject else ''}
                            {f'''<td style="padding: 10px; border: 1px solid #ddd;">{remark if remark else ''}</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{supplier_note if supplier_note else ''}</td>''' if show_notes else ''}
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

            message.attach(MIMEText(html_content, 'html', 'utf-8'))

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

    def send_order_confirmation(self, recipient_email, order_data):
        return self._send_email(
            recipient_email=recipient_email,
            subject='訂單下單通知',
            title='訂單下單通知',
            content_data=order_data,
            is_order_items=True,
            show_notes=False
        )

    def send_order_cancellation(self, recipient_email, order_data):
        return self._send_email(
            recipient_email=recipient_email,
            subject='訂單取消通知',
            title='訂單取消通知',
            content_data=order_data,
            is_order_items=True,
            show_notes=False
        )

    def send_order_approved(self, recipient_email, order_data):
        return self._send_email(
            recipient_email=recipient_email,
            subject='訂單已確認通知',
            title='訂單已確認通知',
            content_data=order_data,
            is_order_items=True,
            show_notes=True
        )

    def send_order_rejected(self, recipient_email, order_data):
        return self._send_email(
            recipient_email=recipient_email,
            subject='訂單已駁回通知',
            title='訂單已駁回通知',
            content_data=order_data,
            is_order_items=True,
            show_notes=True
        )

    def send_order_shipped(self, recipient_email, order_data):
        return self._send_email(
            recipient_email=recipient_email,
            subject='訂單已出貨通知',
            title='訂單已出貨通知',
            content_data=order_data,
            is_order_items=True,
            show_notes=True
        ) 