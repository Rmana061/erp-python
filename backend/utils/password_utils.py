import bcrypt

def hash_password(password):
    """對密碼進行加密"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password, hashed_password):
    """驗證密碼"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8')) 