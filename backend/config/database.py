import psycopg2
from psycopg2 import pool
from contextlib import contextmanager

# 創建全局連接池
connection_pool = pool.SimpleConnectionPool(
    minconn=5,      # 最小連接數
    maxconn=50,     # 增加最大連接數
    host="127.0.0.1",
    port="5432",
    user="postgres",
    password="1qaz2wsx",
    database="postgres"
)

@contextmanager
def get_db_connection():
    conn = None
    try:
        conn = connection_pool.getconn()
        yield conn
    except Exception as e:
        print(f"Database connection error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            try:
                connection_pool.putconn(conn)
            except Exception as e:
                print(f"Error returning connection to pool: {e}")

# 保留舊的函數以保持向後兼容
def release_db_connection(conn):
    try:
        if conn is not None:
            connection_pool.putconn(conn)
            print("Database connection returned to pool.")
    except Exception as e:
        print(f"Error returning connection to pool: {e}") 