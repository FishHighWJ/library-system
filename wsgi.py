"""
WSGI 入口文件 - 用于 PythonAnywhere 部署
PythonAnywhere 会自动加载此文件中的 application 变量

使用方法：
1. 确保下面的路径与你的 PythonAnywhere 用户名一致
2. 如果代码直接在主目录，路径为 '/home/用户名'
3. 如果代码在子文件夹，路径为 '/home/用户名/子文件夹名'
"""

import os
import sys

# 设置生产环境配置
os.environ['FLASK_CONFIG'] = 'production'

# 添加项目路径（把 fishhigh 改成你的 PythonAnywhere 用户名）
# 如果代码直接上传到主目录，用 '/home/fishhigh'
# 如果代码在 library_system 子文件夹，用 '/home/fishhigh/library_system'
project_path = '/home/fishhigh'
if project_path not in sys.path:
    sys.path.insert(0, project_path)

from app import app as application
