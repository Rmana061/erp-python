import json
import time
import threading
import uuid  # 添加uuid模块
import traceback  # 添加用于异常跟踪的模块
from typing import Dict, Any, Optional, List
from .base_log_service import BaseLogService

class OrderLogService(BaseLogService):
    """訂單日誌服務類，處理訂單相關的日誌邏輯"""
    
    def __init__(self, db_connection=None):
        """初始化訂單日誌服務
        
        Args:
            db_connection: 數據庫連接對象
        """
        super().__init__(db_connection)
        # 使用字典按訂單號存儲變更
        self._buffer = {}  
        # 記錄每個訂單的最後日誌時間
        self._last_log_time = {}  
        # 用於定時清理過期緩衝的計時器
        self._timers = {}
        # 全局鎖，用於同步訪問緩衝區
        self._global_lock = threading.Lock()
        # 已處理訂單鎖，用於防止重複處理
        self._processed_lock = threading.Lock()
        # 已處理訂單記錄，用於防止短時間內重複處理同一訂單
        self._processed_orders = {}
        # 啟動監控線程
        self._start_monitor_thread()
        
    def _start_monitor_thread(self):
        """啟動監控線程，定期檢查並處理過期的緩衝項"""
        def monitor_buffers():
            while True:
                try:
                    # 檢查並處理過期的緩衝項
                    self._check_expired_buffers()
                    # 每秒檢查一次
                    time.sleep(1)
                except Exception as e:
                    print(f"監控線程錯誤: {str(e)}")
        
        # 創建並啟動監控線程
        monitor_thread = threading.Thread(target=monitor_buffers, daemon=True)
        monitor_thread.start()
        print("訂單日誌監控線程已啟動")
        
    def _check_expired_buffers(self):
        """檢查並處理過期的緩衝項"""
        try:
            current_time = time.time()
            expired_keys = []
            
            with self._global_lock:
                for key, last_time in list(self._last_log_time.items()):
                    if current_time - last_time > 10:  # 10秒未更新則視為過期
                        expired_keys.append(key)
                        print(f"處理過期緩衝項: {key}")
                        try:
                            self._process_buffer_item(key)
                        except Exception as e:
                            print(f"處理過期緩衝項 {key} 出錯: {str(e)}")
        except Exception as e:
            print(f"檢查過期緩衝項出錯: {str(e)}")
    
    def _normalize_order_number(self, order_number):
        """標準化訂單號，去除前綴"""
        if not order_number:
            return ""
        if order_number.startswith("T"):
            return order_number[1:]
        return order_number
    
    def log_operation(self, table_name: str, operation_type: str, record_id: int, 
                     old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]],
                     performed_by: int, user_type: str) -> bool:
        """記錄訂單操作日誌，支持合併同一訂單的多個變更"""
        try:
            print(f"訂單日誌服務收到操作請求:")
            print(f"表: {table_name}, 操作: {operation_type}, 記錄ID: {record_id}")
            print(f"新數據: {json.dumps(new_data, ensure_ascii=False, indent=2) if new_data else None}")
            
            # 對於非修改操作，直接使用基類方法
            if operation_type != '修改':
                return super().log_operation(table_name, operation_type, record_id, old_data, new_data, performed_by, user_type)
            
            # 獲取訂單號
            order_number = None
            if new_data and isinstance(new_data, dict) and 'message' in new_data:
                if isinstance(new_data['message'], dict) and 'order_number' in new_data['message']:
                    order_number = new_data['message']['order_number']
            
            if not order_number:
                print("無法獲取訂單號，使用基類方法記錄日誌")
                return super().log_operation(table_name, operation_type, record_id, old_data, new_data, performed_by, user_type)
            
            # 標準化訂單號
            normalized_order_number = self._normalize_order_number(order_number)
            buffer_key = f"{table_name}:{normalized_order_number}"
            
            # 生成請求ID，用於日誌追蹤
            request_id = str(uuid.uuid4())[:8]
            print(f"請求ID {request_id}: 處理訂單 {order_number} 的變更")
            
            # 在检查缓冲区前引入短暂延迟，增加并发请求被合并的可能性
            # 这个延迟时间很短，不会明显影响性能，但可以减少重复日志
            time.sleep(0.05)  # 50毫秒延迟
            
            # 關鍵改進：使用單一的鎖處理整個操作流程
            with self._global_lock:
                # 處理現有緩衝項或創建新的緩衝項
                current_time = time.time()
                
                # 首先檢查是否是剛處理過的訂單 (使用更短的過期時間，減少重複記錄的可能)
                with self._processed_lock:
                    if buffer_key in self._processed_orders:
                        elapsed = current_time - self._processed_orders[buffer_key]
                        if elapsed < 0.5:  # 500毫秒內已處理過
                            print(f"請求ID {request_id}: 訂單 {order_number} 剛剛被處理過 ({elapsed:.3f}秒前)，跳過本次記錄")
                            return True
                
                # 檢查緩衝區中是否已有此訂單的變更
                if buffer_key in self._buffer:
                    print(f"請求ID {request_id}: 合併到現有緩衝項")
                    
                    try:
                        # 合併變更到現有緩衝項
                        buffer_data = self._buffer[buffer_key]
                        
                        # 確保緩衝區有 order_logs 字段
                        if 'order_logs' not in buffer_data:
                            buffer_data['order_logs'] = []
                        
                        # 檢查是否為重複日誌
                        is_duplicate = False
                        for existing_log in buffer_data['order_logs']:
                            if existing_log == new_data:
                                print(f"請求ID {request_id}: 發現重複的日誌，跳過")
                                is_duplicate = True
                                break
                        
                        if not is_duplicate:
                            # 添加到日誌列表
                            buffer_data['order_logs'].append(new_data)
                            print(f"請求ID {request_id}: 添加到現有緩衝項，現有 {len(buffer_data['order_logs'])} 條日誌")
                            
                            # 合併產品變更
                            all_products = []
                            for log in buffer_data['order_logs']:
                                if isinstance(log, dict) and 'message' in log:
                                    message = log['message']
                                    if isinstance(message, dict) and 'products' in message:
                                        products = message['products']
                                        if products:
                                            all_products.extend(products)
                            
                            # 按產品ID分組
                            product_map = {}
                            for product in all_products:
                                detail_id = product.get('detail_id')
                                if detail_id:
                                    product_map[detail_id] = product
                            
                            # 更新合併後的數據
                            merged_message = {
                                'order_number': order_number,
                                'products': list(product_map.values())
                            }
                            
                            merged_data = {
                                'message': merged_message,
                                'operation_type': operation_type
                            }
                            
                            # 更新緩衝區數據
                            buffer_data['new_data'] = merged_data
                            print(f"請求ID {request_id}: 更新合併後數據，含 {len(product_map)} 個產品變更")
                    except Exception as e:
                        print(f"請求ID {request_id}: 合併緩衝項時出錯: {str(e)}")
                        print(traceback.format_exc())
                    
                    # 重設定時器
                    if buffer_key in self._timers and self._timers[buffer_key]:
                        self._timers[buffer_key].cancel()
                    
                    # 設置較短的延遲時間，避免等待太久
                    delay = max(0.5, min(2.0, len(buffer_data['order_logs']) * 0.3))
                    print(f"請求ID {request_id}: 設置 {delay:.1f} 秒後處理")
                    
                    timer = threading.Timer(delay, self._process_buffer_item, args=[buffer_key])
                    timer.daemon = True
                    self._timers[buffer_key] = timer
                    timer.start()
                else:
                    # 創建新的緩衝項
                    print(f"請求ID {request_id}: 創建新緩衝項")
                    self._buffer[buffer_key] = {
                        'table_name': table_name,
                        'operation_type': operation_type,
                        'record_id': record_id,
                        'old_data': old_data,
                        'new_data': new_data,
                        'performed_by': performed_by,
                        'user_type': user_type,
                        'order_logs': [new_data],
                        'created_at': current_time,
                        'request_id': request_id  # 添加请求ID方便跟踪
                    }
                    
                    # 設置處理定時器
                    # 对于新建的缓冲项，使用固定的短延迟
                    delay = 1.0  # 固定1秒延迟
                    print(f"請求ID {request_id}: 設置 {delay:.1f} 秒後處理")
                    
                    timer = threading.Timer(delay, self._process_buffer_item, args=[buffer_key])
                    timer.daemon = True
                    self._timers[buffer_key] = timer
                    timer.start()
                
                # 更新最後日誌時間
                self._last_log_time[buffer_key] = current_time
            
            return True
        
        except Exception as e:
            print(f"記錄訂單日誌時發生錯誤: {str(e)}")
            print(traceback.format_exc())
            # 出錯時嘗試使用基類方法記錄
            return super().log_operation(table_name, operation_type, record_id, old_data, new_data, performed_by, user_type)
    
    def _process_buffer_item(self, buffer_key):
        """處理緩衝項，合併同一訂單的多個變更並記錄日誌"""
        try:
            # 在处理前引入短暂延迟，为可能的后续请求提供合并机会
            time.sleep(0.05)  # 50毫秒延迟
            
            # 首先獲取緩衝項並立即標記為已處理，避免重複處理
            buffer_data = None
            request_id = "未知"
            
            with self._global_lock:
                if buffer_key not in self._buffer:
                    print(f"緩衝項 {buffer_key} 不存在或已被處理")
                    return
                
                # 獲取並移除緩衝項
                buffer_data = self._buffer.pop(buffer_key, None)
                
                # 提取请求ID用于日志跟踪
                request_id = buffer_data.get('request_id', '未知')
                
                # 清理相關資源
                if buffer_key in self._last_log_time:
                    del self._last_log_time[buffer_key]
                
                if buffer_key in self._timers and self._timers[buffer_key]:
                    self._timers[buffer_key].cancel()
                    self._timers[buffer_key] = None
            
            if not buffer_data:
                print(f"請求ID {request_id}: 緩衝項 {buffer_key} 數據為空")
                return
            
            # 提取必要信息
            table_name = buffer_data.get('table_name')
            operation_type = buffer_data.get('operation_type')
            record_id = buffer_data.get('record_id')
            performed_by = buffer_data.get('performed_by')
            user_type = buffer_data.get('user_type')
            
            print(f"請求ID {request_id}: 處理緩衝項 {buffer_key}，包含 {len(buffer_data.get('order_logs', []))} 條日誌")
            
            try:
                # 首先尝试使用合并后的数据
                if 'new_data' in buffer_data and buffer_data['new_data']:
                    print(f"請求ID {request_id}: 使用合併後的數據記錄日誌")
                    new_data = buffer_data['new_data']
                    
                    if isinstance(new_data, dict) and 'message' in new_data and 'products' in new_data['message']:
                        products = new_data['message']['products']
                        print(f"請求ID {request_id}: 記錄含 {len(products)} 個產品變更的日誌")
                    
                    # 调用基类方法记录日志
                    result = super().log_operation(
                        table_name, operation_type, record_id,
                        None,  # 合并操作不需要旧数据
                        new_data,
                        performed_by, user_type
                    )
                    print(f"請求ID {request_id}: 日誌記錄結果 - {'成功' if result else '失敗'}")
                    
                    # 标记为已处理
                    with self._processed_lock:
                        self._processed_orders[buffer_key] = time.time()
                        # 延长过期时间到10秒，避免快速请求导致的问题
                        # 在过期检查方法中会清理这些记录
                        self._processed_order_expiry = 10.0  # 10秒过期
                    
                    return result
                else:
                    print(f"請求ID {request_id}: 緩衝項中沒有合併數據，使用最後一條日誌")
                    # 如果没有合并数据，使用最后一条日志
                    if 'order_logs' in buffer_data and buffer_data['order_logs']:
                        last_log = buffer_data['order_logs'][-1]
                        result = super().log_operation(
                            table_name, operation_type, record_id,
                            None, last_log,
                            performed_by, user_type
                        )
                        
                        with self._processed_lock:
                            self._processed_orders[buffer_key] = time.time()
                            self._processed_order_expiry = 10.0
                        
                        return result
            except Exception as e:
                print(f"請求ID {request_id}: 處理緩衝項時出錯: {str(e)}")
                print(traceback.format_exc())
                
                # 出错时尝试使用原始数据
                try:
                    old_data = buffer_data.get('old_data')
                    original_new_data = buffer_data.get('new_data')
                    
                    print(f"請求ID {request_id}: 嘗試使用原始數據記錄日誌")
                    return super().log_operation(
                        table_name, operation_type, record_id,
                        old_data, original_new_data,
                        performed_by, user_type
                    )
                except Exception as e2:
                    print(f"請求ID {request_id}: 使用原始數據記錄日誌時出錯: {str(e2)}")
                    print(traceback.format_exc())
                    return False
        
        except Exception as e:
            print(f"處理緩衝項時發生未預期錯誤: {str(e)}")
            print(traceback.format_exc())
            return False
    
    def _extract_products_from_log(self, log_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """從日誌數據中提取產品信息"""
        products = []
        
        # 如果log_data有message字段
        message = log_data.get('message', {})
        
        # 如果message是字典且包含products字段
        if isinstance(message, dict) and 'products' in message:
            products = message.get('products', [])
        
        # 如果message是字符串，嘗試解析
        elif isinstance(message, str) and message:
            try:
                # 嘗試將字符串解析為產品信息
                parts = {}
                for part in message.split('、'):
                    if ':' in part:
                        key, value = part.split(':', 1)
                        parts[key.strip()] = value.strip()
                
                # 如果解析出產品名稱，構建產品對象
                if '產品' in parts:
                    product = {
                        'name': parts.get('產品', ''),
                        'quantity': parts.get('數量', ''),
                        'shipping_date': parts.get('出貨日期', '待確認'),
                        'remark': parts.get('備註', '-'),
                        'supplier_note': parts.get('供應商備註', '-'),
                        'status': parts.get('狀態', '待確認')
                    }
                    products.append(product)
            except Exception as e:
                print(f"解析產品信息失敗: {str(e)}")
        
        return products
    
    def _process_modify_logs(self, buffer_key, order_logs, modify_log):
        """處理修改操作的日誌，合併同一訂單的多個產品變更"""
        try:
            # 獲取訂單號
            order_number = None
            if modify_log and isinstance(modify_log, dict) and 'message' in modify_log:
                if isinstance(modify_log['message'], dict) and 'order_number' in modify_log['message']:
                    order_number = modify_log['message']['order_number']
            
            if not order_number:
                print("無法獲取訂單號，返回原始日誌數據")
                return modify_log
            
            # 收集所有產品變更
            all_products = []
            
            # 從所有日誌中收集產品變更
            for log in order_logs:
                products = self._extract_products_from_log(log)
                all_products.extend(products)
            
            # 如果沒有收集到產品變更，使用原始數據
            if not all_products and modify_log:
                products = self._extract_products_from_log(modify_log)
                all_products.extend(products)
            
            print(f"收集到 {len(all_products)} 個產品變更")
            
            # 合併相同產品的變更
            merged_products = []
            product_map = {}
            
            for product in all_products:
                # 使用產品名稱和detail_id作為唯一標識
                product_key = None
                if 'detail_id' in product:
                    product_key = f"{product.get('name', '')}:{product['detail_id']}"
                elif 'name' in product:
                    product_key = product['name']
                
                if not product_key:
                    continue
                
                if product_key in product_map:
                    # 合併變更
                    if 'changes' in product and 'changes' in product_map[product_key]:
                        product_map[product_key]['changes'].update(product['changes'])
                else:
                    # 添加新產品
                    product_map[product_key] = product
            
            # 將合併後的產品添加到結果中
            merged_products = list(product_map.values())
            print(f"合併後有 {len(merged_products)} 個產品")
            
            # 構建最終的合併數據
            merged_data = {
                'message': {
                    'order_number': order_number,
                    'products': merged_products
                },
                'operation_type': '修改'
            }
            
            print(f"最終合併數據: {json.dumps(merged_data, ensure_ascii=False, indent=2)}")
            return merged_data
            
        except Exception as e:
            print(f"處理修改日誌錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            return modify_log
        
    def _get_changes(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]], operation_type: str = None) -> Dict[str, Any]:
        """處理訂單變更的方法"""
        print(f"處理訂單變更 - 操作類型: {operation_type}")

        try:
            # 處理新增和刪除操作
            if operation_type in ['新增', '刪除']:
                return self._process_create_delete(operation_type, old_data, new_data)
            
            # 處理審核操作
            if operation_type == '審核':
                return self._process_audit(old_data, new_data)
            
            # 處理修改操作
            if operation_type == '修改' and new_data:
                # 如果 new_data 包含 message 字段，直接使用它
                if isinstance(new_data, dict) and 'message' in new_data:
                    # 確保返回的數據包含 operation_type
                    if 'operation_type' not in new_data:
                        new_data['operation_type'] = operation_type
                    
                    return new_data
                
                # 如果沒有 message 字段，嘗試處理更新操作
                if old_data:
                    return self._process_update(old_data, new_data)
                else:
                    # 如果沒有 old_data，但有 new_data 和 operation_type，創建一個基本的變更記錄
                    return {
                        'message': new_data.get('message', {'products': []}),
                        'operation_type': operation_type
                    }
        except Exception as e:
            print(f"處理變更錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'message': '處理變更時發生錯誤', 'operation_type': None}
        
        return {'message': '無變更', 'operation_type': None}

    def _process_create_delete(self, operation_type: str, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """處理新增和刪除操作"""
        try:
            data = new_data if operation_type == '新增' else old_data
            if isinstance(data, dict) and 'message' in data:
                message = data['message']
                # 如果 message 是 JSON 字符串，先解析它
                if isinstance(message, str):
                    try:
                        message = json.loads(message)
                    except json.JSONDecodeError:
                        print("無法解析 JSON 消息")
                        return {'message': '無變更', 'operation_type': None}
                
                if isinstance(message, dict):
                    # 確保返回的格式與原始格式一致
                    return {
                        'message': {
                            'status': message.get('status', '待確認'),
                            'products': message.get('products', []),
                            'order_number': message.get('order_number', '')
                        },
                        'operation_type': operation_type
                    }
            
        except Exception as e:
            print(f"處理新增/刪除操作錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
        return {'message': '無變更', 'operation_type': None}
    
    def _process_audit(self, old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """處理審核操作"""
        try:
            # 如果新數據是字典格式且包含完整的審核信息
            if isinstance(new_data, dict) and isinstance(new_data.get('message'), dict):
                message = new_data['message']
                
                # 從新數據中獲取狀態變更信息
                if 'status' in message and isinstance(message['status'], dict):
                    # 如果已經包含了完整的狀態變更信息，直接使用
                    return {
                        'message': {
                            'order_number': message.get('order_number', ''),
                            'status': message['status']
                        },
                        'operation_type': '審核'
                    }
                else:
                    # 從舊數據中獲取之前的狀態
                    old_status = '待確認'
                    if isinstance(old_data, dict) and isinstance(old_data.get('message'), str):
                        parts = old_data['message'].split('、')
                        for part in parts:
                            if '狀態:' in part:
                                old_status = part.split(':', 1)[1].strip()
                                break
                    
                    # 從新數據中獲取當前狀態
                    new_status = message.get('status', '已確認')
                    if isinstance(new_status, str):
                        return {
                            'message': {
                                'order_number': message.get('order_number', ''),
                                'status': {
                                    'before': old_status,
                                    'after': new_status
                                }
                            },
                            'operation_type': '審核'
                        }
            
            # 如果是舊格式的字符串消息
            if isinstance(old_data, dict) and isinstance(old_data.get('message'), str):
                order_number = ''
                old_status = '待確認'
                parts = old_data['message'].split('、')
                for part in parts:
                    if '訂單號:' in part:
                        order_number = part.split(':', 1)[1].strip()
                    elif '狀態:' in part:
                        old_status = part.split(':', 1)[1].strip()
                
                # 從新數據中獲取目標狀態
                new_status = '已確認'
                if isinstance(new_data, dict) and isinstance(new_data.get('message'), dict):
                    if 'status' in new_data['message']:
                        if isinstance(new_data['message']['status'], dict):
                            new_status = new_data['message']['status'].get('after', '已確認')
                        else:
                            new_status = new_data['message']['status']
                
                return {
                    'message': {
                        'order_number': order_number,
                        'status': {
                            'before': old_status,
                            'after': new_status
                        }
                    },
                    'operation_type': '審核'
                }
            
            return {'message': '無變更', 'operation_type': None}
            
        except Exception as e:
            print(f"處理審核操作錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'message': '無變更', 'operation_type': None}

    def _process_update(self, old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理修改操作的變更记录"""
        old_message = old_data.get('message', '')
        new_message = new_data.get('message', '')

        # 从消息中提取产品信息
        try:
            # 尝试解析和比较产品列表
            old_products = self._extract_products_from_log(old_data)
            new_products = self._extract_products_from_log(new_data)
            
            # 生成变更详情
            changes = {}
            products_with_changes = []
            
            # 对比产品变更
            if old_products and new_products:
                # 创建产品ID到产品映射
                old_products_map = {p.get('id'): p for p in old_products if p.get('id')}
                new_products_map = {p.get('id'): p for p in new_products if p.get('id')}
                
                # 找出所有产品ID
                all_product_ids = set(list(old_products_map.keys()) + list(new_products_map.keys()))
                
                for product_id in all_product_ids:
                    old_product = old_products_map.get(product_id, {})
                    new_product = new_products_map.get(product_id, {})
                    
                    # 如果产品在两个列表中都存在，比较变更
                    if old_product and new_product:
                        product_changes = self._compare_products(old_product, new_product)
                        if product_changes:
                            products_with_changes.append({
                                'id': product_id,
                                'name': new_product.get('name', old_product.get('name', '')),
                                'changes': product_changes,
                                'quantity': new_product.get('quantity'),
                                'shipping_date': new_product.get('shipping_date'),
                                'remark': new_product.get('remark'),
                                'supplier_note': new_product.get('supplier_note')
                            })
            
            # 如果有状态变更，添加到变更列表
            if old_data.get('status') != new_data.get('status'):
                changes['status'] = {
                    'before': old_data.get('status', ''),
                    'after': new_data.get('status', '')
                }
            
            # 构建返回结果
            result = {
                    'message': {
                    'order_number': new_data.get('order_number', old_data.get('order_number', '')),
                    'products': products_with_changes
                    },
                    'operation_type': '修改'
                }

            # 添加状态变更
            if changes.get('status'):
                result['message']['status'] = changes['status']
            
            return result
        except Exception as e:
            print(f"Error processing update: {str(e)}")
            return {
                'message': '无法处理修改记录',
                'operation_type': '修改'
            }

    def _compare_products(self, old_product: Dict[str, Any], new_product: Dict[str, Any]) -> Dict[str, Any]:
        """比较两个产品对象之间的差异"""
        changes = {}
        
        # 需要比较的字段
        fields_to_compare = [
            ('quantity', '數量'),
            ('shipping_date', '出貨日期'),
            ('remark', '備註'),
            ('supplier_note', '供應商備註'),
            ('status', '狀態')
        ]
        
        # 对每个字段进行比较
        for field, _ in fields_to_compare:
            old_value = old_product.get(field, '')
            new_value = new_product.get(field, '')
            
            # 只有在值不同时才记录变更
            if old_value != new_value:
                changes[field] = {
                    'before': old_value,
                    'after': new_value
                }
        
        return changes