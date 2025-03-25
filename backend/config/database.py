import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
import logging

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 修改連接池配置
connection_pool = pool.SimpleConnectionPool(
    minconn=5,
    maxconn=50,
    host="127.0.0.1",
    port="5432",
    user="postgres",
    password="1qaz2wsx",
    database="postgres",
    # 添加連接超時設置
    connect_timeout=3,
    # 添加自動重連
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5
)

@contextmanager
def get_db_connection():
    conn = None
    retries = 0
    max_retries = 3
    
    while retries < max_retries:
        try:
            conn = connection_pool.getconn()
            # 檢查連接是否有效
            if conn.closed:
                logger.warning("檢測到已關閉的連接，嘗試重新獲取")
                connection_pool.putconn(conn)
                conn = connection_pool.getconn()
            
            # 測試連接是否真的可用
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            
            yield conn
            break  # 如果成功獲取連接，跳出重試循環
            
        except psycopg2.OperationalError as e:
            logger.error(f"資料庫操作錯誤 (嘗試 {retries + 1}/{max_retries}): {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    connection_pool.putconn(conn)
                except Exception:
                    pass
            retries += 1
            if retries >= max_retries:
                raise
                
        except psycopg2.InterfaceError as e:
            logger.error(f"資料庫接口錯誤 (嘗試 {retries + 1}/{max_retries}): {e}")
            if conn:
                try:
                    connection_pool.putconn(conn)
                except Exception:
                    pass
            conn = connection_pool.getconn()  # 重新獲取連接
            retries += 1
            if retries >= max_retries:
                raise
                
        except Exception as e:
            logger.error(f"資料庫連接錯誤: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
            
    if conn:  # 確保在最後總是嘗試歸還連接
        try:
            if not conn.closed:
                connection_pool.putconn(conn)
                logger.debug("連接已歸還到連接池")
        except Exception as e:
            logger.error(f"歸還連接到連接池時發生錯誤: {e}")

# 保留舊的函數以保持向後兼容
def release_db_connection(conn):
    try:
        if conn is not None and not conn.closed:
            connection_pool.putconn(conn)
            logger.debug("Database connection returned to pool.")
    except Exception as e:
        logger.error(f"Error returning connection to pool: {e}") 