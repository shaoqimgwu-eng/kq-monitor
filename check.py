"""
考勤自动检测 - 多账号版
每天17:10依次检查所有账号的打卡状态
支持随时添加/删除账号
"""
import json
from datetime import datetime, date, timezone, timedelta
import requests
import urllib3
urllib3.disable_warnings()

# ============ 配置 ============
LOGIN_API = "https://kqedcall.kq.gov.cn:13007/api/auth/v2/login"
CHECK_API = "https://kqedcall.kq.gov.cn:13007/api/hall2/checking/query"

# Server酱 SendKey
SCT_SENDKEY = "SCT360493TFyvzipRSGn30n5E93S0aXnbB"

# ============ 账号列表（按需增删） ============
# 优先从 accounts.json 加载，文件不存在则使用下方硬编码列表
# 格式: [{"username": "账号", "password": "密码", "name": "显示名称"}]
import os as _os

def _load_accounts() -> list:
    """加载账号列表：优先 accounts.json，否则用默认列表"""
    json_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "accounts.json")
    if _os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
            print(f"[配置] 从 accounts.json 加载了 {len(accounts)} 个账号")
            return accounts
        except Exception as e:
            print(f"[配置] accounts.json 解析失败: {e}，使用默认列表")
    return _DEFAULT_ACCOUNTS

_DEFAULT_ACCOUNTS = [
    {"username": "fengyt", "password": "1234.1234", "name": "冯艳涛"},
    {"username": "wusq",   "password": "12341234", "name": "wusq"},
    # 后续添加更多账号只需在 accounts.json 中加一行
]

ACCOUNTS = _load_accounts()

# 北京时间时区
CST = timezone(timedelta(hours=8))


# ============ 节假日判断 ============
def is_workday(d: date) -> bool:
    """判断法定工作日（含调休补班）"""
    date_str = d.strftime("%Y-%m-%d")
    try:
        r = requests.get(
            f"https://timor.tech/api/holiday/info/{date_str}", timeout=5
        )
        data = r.json()
    except:
        # 无法判断时，按周一到周五处理
        return d.weekday() < 5

    if d.weekday() >= 5:
        # 周末 → 检查是否为调休补班
        if data.get("type", {}).get("type") == 0 and data.get("holiday"):
            return True
        return False
    # 工作日 → 检查是否为法定假日
    if data.get("holiday"):
        return False
    return True


# ============ 通知 ============
_notified_messages = []  # 汇总所有通知

def add_notification(title: str, content: str):
    """添加一条通知到汇总列表"""
    _notified_messages.append({"title": title, "content": content})


def send_summary():
    """发送汇总通知"""
    if not _notified_messages:
        return

    if len(_notified_messages) == 1:
        title = _notified_messages[0]["title"]
        content = _notified_messages[0]["content"]
    else:
        title = f"考勤异常 - {len(_notified_messages)}个账号"
        content = "\n\n---\n\n".join(
            f"### {m['title']}\n{m['content']}" for m in _notified_messages
        )

    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{SCT_SENDKEY}.send",
            data={"title": title, "desp": content},
            timeout=10,
        )
        if r.json().get("code") == 0:
            print(f"[通知] ✓ 微信推送成功")
        else:
            print(f"[通知] ✗ 推送失败: {r.json()}")
    except Exception as e:
        print(f"[通知] ✗ 异常: {e}")


# ============ 单账号检查 ============
def check_one(account: dict, today: date) -> None:
    """检查单个账号的打卡状态"""
    name = account["name"]
    username = account["username"]

    print(f"\n--- [{name}] {username} ---")

    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "X-Commnet-Device": "kq-check-bot",
    })

    # 1. 登录
    try:
        r = session.post(
            LOGIN_API,
            json={"username": username, "pwd": account["password"]},
            timeout=15,
        )
        data = r.json()
    except Exception as e:
        print(f"  ✗ 登录请求失败: {e}")
        add_notification(
            f"❌ [{name}] 登录失败",
            f"账号 {username} 登录请求异常: {e}"
        )
        return

    if data.get("code") != "success":
        error_msg = data.get("desc", data.get("message", str(data)))
        # 尝试解码中文
        print(f"  ✗ 登录失败: {error_msg}")
        add_notification(
            f"❌ [{name}] 登录失败",
            f"账号 **{username}** 登录失败:\n\n{error_msg}\n\n可能是密码错误或账号被锁定"
        )
        return

    jwt = data["result"]["jwt"]
    actual_name = data["result"].get("username", name)
    session.headers["X-Commnet-Token"] = jwt
    print(f"  ✓ 登录成功 ({actual_name})")

    # 2. 查询考勤
    today_str = today.strftime("%Y-%m-%d")
    try:
        r = session.post(CHECK_API, json={
            "endtime": today_str,
            "starttime": today_str,
            "nodeid": 1,
            "orders": [{"orderby": "checkdate", "ordertype": "DESC"}],
            "needtotal": True,
            "pagenum": 1,
            "pagesize": 10,
        }, timeout=15)
        result = r.json()
    except Exception as e:
        print(f"  ✗ 考勤查询失败: {e}")
        add_notification(
            f"❌ [{name}] 查询失败",
            f"账号 {username} 考勤查询异常: {e}"
        )
        return

    if result.get("code") != "success":
        print(f"  ✗ 查询返回异常: {result}")
        return

    # 3. 分析打卡状态
    # 关键: 有 morningtime/afternoontime → 已打卡，无 → 未打卡
    # 数值含义: 0=未打卡 1=正常 2=迟到 3=外勤 等
    records = result.get("result", {}).get("rows", [])
    total = result.get("result", {}).get("total", 0)
    print(f"  记录数: {total}")

    if total == 0:
        print(f"  ⚠️ 今日无打卡记录！")
        add_notification(
            f"⚠️ [{name}] 今日未打卡",
            f"**账号**: {username} ({actual_name})\n"
            f"**日期**: {today}\n"
            f"**状态**: 全天无任何打卡记录\n"
            f"**检测时间**: {datetime.now(CST).strftime('%H:%M:%S')}\n\n"
            f"> 请立即补卡！"
        )
        return

    for rec in records:
        morning_time = rec.get("morningtime", "")
        afternoon_time = rec.get("afternoontime", "")
        night_time = rec.get("nighttime", "")
        noon_time = rec.get("noontime", "")

        # 用时间戳判断是否打卡
        morning_ok = bool(morning_time)
        afternoon_ok = bool(afternoon_time)
        night_ok = bool(night_time)

        print(f"    上午: {'✓ '+morning_time if morning_ok else '✗ 未打卡'}")
        print(f"    下午: {'✓ '+afternoon_time if afternoon_ok else '✗ 未打卡'}")
        if night_time:
            print(f"    晚上: ✓ {night_time}")

        # 如果没有任何时间戳，可能是休息日或异常
        if not morning_ok and not afternoon_ok and not night_ok:
            print(f"  → 全天无打卡")
            add_notification(
                f"⚠️ [{name}] 今日未打卡",
                f"**账号**: {username} ({actual_name})\n"
                f"**日期**: {today}\n"
                f"**状态**: 全天无打卡记录\n"
                f"**检测时间**: {datetime.now(CST).strftime('%H:%M:%S')}\n\n"
                f"> 请立即补卡！"
            )
            return

        missing = []
        detail = []
        if not morning_ok:
            missing.append("上午(上班)")
            detail.append(f"上午: ❌ 未打卡")
        else:
            detail.append(f"上午: ✓ {morning_time}")
        if not afternoon_ok:
            missing.append("下午(下班)")
            detail.append(f"下午: ❌ 未打卡")
        else:
            detail.append(f"下午: ✓ {afternoon_time}")
        if night_time:
            detail.append(f"晚上: ✓ {night_time}")

        if missing:
            print(f"  ⚠️ 缺卡: {missing}")
            add_notification(
                f"⚠️ [{name}] 打卡异常",
                f"**账号**: {username} ({actual_name})\n"
                f"**日期**: {today}\n"
                f"**未打卡**: {'、'.join(missing)}\n"
                f"**详情**:\n" + "\n".join(detail) + "\n\n"
                f"**检测时间**: {datetime.now(CST).strftime('%H:%M:%S')}\n\n"
                f"> 请立即补卡！"
            )
        else:
            print(f"  ✓ 打卡正常")


def _status_text(val: int) -> str:
    return {0: "❌ 未打卡", 1: "✓ 正常", 2: "⚠️ 迟到", 3: "— 休息"}.get(val, f"未知({val})")


# ============ 主流程 ============
def main():
    now = datetime.now(CST)
    today = now.date()
    print(f"{'='*50}")
    print(f"  考勤检查 {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"  账号数量: {len(ACCOUNTS)}")
    print(f"{'='*50}")

    if not is_workday(today):
        holiday_info = ""
        try:
            r = requests.get(f"https://timor.tech/api/holiday/info/{today.strftime('%Y-%m-%d')}", timeout=5)
            h = r.json().get("holiday", {})
            if h:
                holiday_info = f" ({h.get('name', '')})"
        except:
            pass
        print(f"非工作日{holiday_info}，跳过所有检查")
        return

    for account in ACCOUNTS:
        check_one(account, today)

    send_summary()
    print(f"\n{'='*50}")
    print(f"  检查完毕 - {datetime.now(CST).strftime('%H:%M:%S')}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
