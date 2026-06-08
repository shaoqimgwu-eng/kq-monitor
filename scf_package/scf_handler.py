"""
腾讯云函数 SCF 入口
定时触发器 -> 调用 check.py 的 main()
"""
import json
import sys
import os

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check import main as check_main


def main_handler(event, context):
    """
    SCF 入口函数
    腾讯云函数定时触发器调用此函数
    """
    print(f"SCF trigger: {json.dumps(event, ensure_ascii=False)}")
    check_main()
    return {"code": 0, "message": "ok"}


if __name__ == "__main__":
    # 本地测试用
    main_handler({}, None)
