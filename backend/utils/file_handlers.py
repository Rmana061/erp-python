import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_DOC_EXTENSIONS = {'pdf', 'doc', 'docx'}

def create_product_folder(product_name):
    """創建產品文件夾"""
    folder_path = os.path.join(UPLOAD_FOLDER, secure_filename(product_name))
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    return folder_path

def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def allowed_doc_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOC_EXTENSIONS 