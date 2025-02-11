import bcrypt

def hash_password(password):
    """
    將密碼進行哈希加密
    :param password: 原始密碼
    :return: 加密後的哈希值
    """
    # 將密碼轉換為 bytes
    password_bytes = password.encode('utf-8')
    # 生成鹽值並加密
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    # 返回加密後的哈希值（轉換為字符串）
    return hashed.decode('utf-8')

def verify_password(password, hashed):
    """
    驗證密碼是否正確
    :param password: 待驗證的密碼
    :param hashed: 存儲的哈希值
    :return: 布爾值，表示密碼是否正確
    """
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8')) 