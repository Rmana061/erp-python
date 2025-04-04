from flask import Blueprint, request, jsonify, session
from ..config.database import get_db_connection
import psycopg2.extras
from datetime import datetime, timedelta
import logging

# 獲取 logger
logger = logging.getLogger(__name__)

order_check_bp = Blueprint('order_check', __name__)

@order_check_bp.route('/orders/check-recent', methods=['POST'])
def check_recent_order():
    """检查客户是否在指定天数内已经订购过相同产品"""
    try:
        data = request.json
        customer_id = data.get('customer_id')
        product_id = data.get('product_id')
        
        if not customer_id or not product_id:
            return jsonify({
                "status": "error",
                "message": "缺少必要参数"
            }), 400
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 获取客户的重复下单限制天数
            cursor.execute("""
                SELECT reorder_limit_days FROM customers 
                WHERE id = %s AND status = 'active'
            """, (customer_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({
                    "status": "error",
                    "message": "找不到客户信息"
                }), 404
            
            limit_days = result[0] or 0
            
            # 如果限制天数为0，表示无限制
            if limit_days <= 0:
                return jsonify({
                    "status": "success",
                    "data": {
                        "can_order": True,
                        "limitDays": 0
                    }
                })
            
            # 查询客户在限制日期内是否订购过该产品
            cursor.execute("""
                SELECT od.id 
                FROM orders o
                JOIN order_details od ON o.id = od.order_id
                WHERE o.customer_id = %s
                  AND od.product_id = %s
                  AND (od.order_status IS NULL OR od.order_status NOT IN ('已取消'))
                  AND o.created_at >= CURRENT_DATE - INTERVAL '%s DAY'
                LIMIT 1
            """, (customer_id, product_id, limit_days))
            
            recent_order = cursor.fetchone()
            
            if recent_order:
                # 找到了最近的订单，不允许下单
                logger.info("找到最近订单: 客户ID=%s, 产品ID=%s, 限制天数=%s", customer_id, product_id, limit_days)
                return jsonify({
                    "status": "success",
                    "data": {
                        "can_order": False,
                        "limit_days": limit_days,
                        "message": f"您在{limit_days}天内已经订购过此产品"
                    }
                })
            
            # 没有找到最近的订单，允许下单
            logger.debug("没有找到最近订单: 客户ID=%s, 产品ID=%s", customer_id, product_id)
            return jsonify({
                "status": "success",
                "data": {
                    "can_order": True,
                    "limit_days": limit_days
                }
            })
            
    except Exception as e:
        logger.error("Error in check_recent_order: %s", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 