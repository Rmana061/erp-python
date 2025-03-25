import logging
import datetime
import sys
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from pytz import timezone
from backend.config.database import get_db_connection
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import psycopg2

# 配置日志系统，同时解决编码问题
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log", encoding='utf-8'),  # 明确指定utf-8编码
        logging.StreamHandler(sys.stdout)  # 使用stdout而不是stderr
    ]
)
logger = logging.getLogger("date_cleaner")

# 全局调度器
scheduler = None

def log_retry(retry_state):
    """自定義重試日誌函數"""
    if retry_state.attempt_number > 1:  # 只在重試時記錄
        logger.info(f"重試清理任務 (第 {retry_state.attempt_number} 次嘗試)")
    return True

# 修改重試裝飾器
@retry(
    stop=stop_after_attempt(5),  # 增加重試次數
    wait=wait_exponential(multiplier=2, min=4, max=60),  # 調整等待時間
    retry=retry_if_exception_type((psycopg2.Error, psycopg2.InterfaceError)),  # 擴大重試的錯誤類型
    before=log_retry  # 使用自定義的日誌函數
)
def clean_expired_dates():
    """清理过期的锁定日期"""
    logger.info("開始執行過期日期清理任務")
    today = datetime.date.today()
    logger.info(f"當前日期: {today.isoformat()}")
    deleted_count = 0
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # 檢查連接狀態
                    if conn.closed:
                        raise psycopg2.InterfaceError("資料庫連接已關閉")
                    
                    # 首先查询所有日期，检查是否有过期日期
                    cursor.execute("SELECT id, locked_date FROM locked_dates ORDER BY locked_date")
                    all_dates = cursor.fetchall()
                    logger.info(f"資料庫中的所有日期: {[row[1].isoformat() for row in all_dates]}")
                    
                    # 查询并删除过期的锁定日期（早于今天的日期）
                    cursor.execute("""
                        DELETE FROM locked_dates 
                        WHERE locked_date < %s::date
                        RETURNING id, locked_date
                    """, (today.isoformat(),))
                    
                    deleted_rows = cursor.fetchall()
                    deleted_count = len(deleted_rows)
                    
                    # 提交事務
                    conn.commit()
                    logger.info(f"已提交事務，刪除了 {deleted_count} 條記錄")
                    
                    if deleted_count > 0:
                        deleted_ids = [row[0] for row in deleted_rows]
                        deleted_dates = [row[1].strftime('%Y-%m-%d') for row in deleted_rows]
                        logger.info(f"已刪除 {deleted_count} 個過期鎖定日期")
                        logger.info(f"已刪除的日期: {', '.join(deleted_dates)}")
                        logger.info(f"已刪除的ID: {', '.join(map(str, deleted_ids))}")
                    else:
                        logger.info("沒有過期的鎖定日期需要清理")
                    
                except Exception as e:
                    conn.rollback()
                    logger.error(f"執行清理任務時發生錯誤，已回滾事務: {str(e)}")
                    raise
                
    except psycopg2.Error as e:
        logger.error(f"資料庫操作錯誤: {str(e)}")
        logger.exception("詳細錯誤信息")
        raise
    except Exception as e:
        logger.error(f"清理過期日期時發生錯誤: {str(e)}")
        logger.exception("詳細錯誤信息")
        raise
    finally:
        logger.info("鎖定日期清理任務結束")
        
    return deleted_count

def job_listener(event):
    """作業執行監聽器"""
    if event.exception:
        logger.error(f"任務執行失敗: {str(event.exception)}")
        logger.exception("詳細錯誤信息", exc_info=event.exception)
    else:
        job_id = event.job_id
        logger.info(f"任務 {job_id} 執行成功，清理了 {event.retval} 個過期日期")

def initialize_scheduler():
    """初始化和启动调度器"""
    global scheduler
    
    if scheduler is not None and scheduler.running:
        logger.info("調度器已經在運行中")
        return scheduler
    
    logger.info("初始化調度器")
    
    try:
        tz = timezone('Asia/Taipei')
        logger.info(f"使用時區: {tz.zone}, 當前時間: {datetime.datetime.now(tz).isoformat()}")
        
        # 修改調度器配置
        scheduler = BackgroundScheduler(
            timezone=tz,
            job_defaults={
                'coalesce': True,  # 合併錯過的任務
                'max_instances': 1,  # 限制同時運行的實例數
                'misfire_grace_time': 300,  # 錯過執行的寬限時間（秒）
                'retry': {  # 添加任務重試配置
                    'max_attempts': 3,
                    'delay': 30
                }
            }
        )
        
        # 添加任务执行监听器
        scheduler.add_listener(
            job_listener, 
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
        
        # 添加定时任务：每天凌晨00:05执行清理
        scheduler.add_job(
            clean_expired_dates,
            CronTrigger(hour=0, minute=5),  # 每天凌晨00:05执行
            id='clean_expired_dates_job',
            name='清理過期鎖定日期任務',
            replace_existing=True,
            max_instances=1  # 確保同一時間只有一個實例在運行
        )
        
        # 添加任务立即执行一次，确保系统启动时就清理过期日期
        scheduler.add_job(
            clean_expired_dates,
            'date',
            run_date=datetime.datetime.now(tz) + datetime.timedelta(seconds=10),
            id='initial_clean_job',
            name='初始清理過期鎖定日期任務',
            max_instances=1
        )
        
        # 启动调度器
        scheduler.start()
        logger.info("調度器已成功啟動")
        
        # 打印已调度的任务
        for job in scheduler.get_jobs():
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "無"
            logger.info(f"已調度任務: {job.id} ({job.name}), 下次執行時間: {next_run}")
        
        return scheduler
    except Exception as e:
        logger.error(f"啟動調度器時發生錯誤: {str(e)}")
        logger.exception("詳細錯誤信息")
        raise

def shutdown_scheduler():
    """关闭调度器"""
    global scheduler
    if scheduler and scheduler.running:
        try:
            scheduler.shutdown(wait=True)  # 等待所有正在運行的任務完成
            logger.info("調度器已正常關閉")
        except Exception as e:
            logger.error(f"關閉調度器時發生錯誤: {str(e)}")
            logger.exception("詳細錯誤信息")
        finally:
            scheduler = None

# 手动执行清理，用于测试
def run_clean_task_manually():
    """手动执行清理任务，用于测试"""
    logger.info("手動執行清理任務")
    try:
        count = clean_expired_dates()
        result = {
            "status": "success", 
            "message": f"手動清理完成，共清理了 {count} 個過期鎖定日期"
        }
        logger.info(f"手動清理結果: {result}")
        return result
    except Exception as e:
        logger.error(f"手動執行清理任務失敗: {str(e)}")
        logger.exception("詳細錯誤信息")
        return {
            "status": "error",
            "message": f"清理失敗: {str(e)}"
        } 