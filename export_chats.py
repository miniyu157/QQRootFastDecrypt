import sqlite3
import blackboxprotobuf
from datetime import datetime
import os
import re
import json

# --- 配置文件 ---
OUTPUT_DIR = "output_chats"  # 导出文件存放的文件夹
C2C_DB_FILE = "nt_msg.decrypt.db"  # 聊天记录数据库
PROFILE_DB_FILE = "profile_info.decrypt.db"  # 好友信息数据库

# --- 表名 ---
C2C_TABLE = "c2c_msg_table"  # 单聊消息表
PROFILE_TABLE = "profile_info_v6"  # 用户信息表
BUDDY_TABLE = "buddy_list"  # 好友列表

# --- 聊天记录表 c2c_msg_table 的列名 ---
C2C_COL_SENDER_UID = "[40020]"  # 发送者UID
C2C_COL_PEER_UID = "[40021]"  # 接收者UID
C2C_COL_MSG_TIME = "[40050]"  # 消息时间戳 (秒)
C2C_COL_MSG_CONTENT = "[40800]"  # 消息内容 (Protobuf)

# --- 好友信息库 profile_info.decrypt.db 的列名 ---
P_COL_UID = '"1000"'  # 通用UID
P_COL_QQ = '"1002"'  # QQ号
P_COL_NAME = '"20002"'  # 昵称
P_COL_REMARK = '"20009"'  # 备注

# --- Protobuf 内部字段ID ---
PB_FIELD_MSG_CONTAINER = "40800"  # 消息容器
PB_FIELD_TEXT = "45101"  # 文本内容
PB_FIELD_REPLY = "47423"  # 回复内容


class ProfileManager:
    """管理好友信息，提供UID和昵称/备注之间的转换。"""

    def __init__(self, profile_db_path):
        self.is_enabled = os.path.exists(profile_db_path)
        self.friends = {}
        self.my_uid = None
        if self.is_enabled:
            print(f"检测到好友信息库 '{profile_db_path}'，启用好友功能。")
            self._load_data(profile_db_path)
        else:
            print(f"未找到好友信息库 '{profile_db_path}'，将仅使用UID。")

    def _load_data(self, db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            profiles = {
                uid: {"name": name, "remark": remark}
                for uid, name, remark in cursor.execute(
                    f"SELECT {P_COL_UID}, {P_COL_NAME}, {P_COL_REMARK} FROM {PROFILE_TABLE}"
                )
            }
            buddies = cursor.execute(
                f"SELECT {P_COL_UID}, {P_COL_QQ} FROM {BUDDY_TABLE}"
            ).fetchall()
            for uid, qq in buddies:
                profile_info = profiles.get(uid, {})
                self.friends[uid] = {
                    "qq": qq,
                    "name": profile_info.get("name", f"未知昵称_{uid[:4]}"),
                    "remark": profile_info.get("remark"),
                }
            print(f"成功加载 {len(self.friends)} 位好友的信息。")
        except sqlite3.Error as e:
            print(f"加载好友信息失败: {e}。已禁用好友功能。")
            self.is_enabled = False
        finally:
            if "conn" in locals() and conn:
                conn.close()

    def find_uid(self, identifier):
        if not self.is_enabled:
            return identifier
        identifier = str(identifier).strip()
        if identifier.startswith("u_"):
            return identifier
        try:
            conn = sqlite3.connect(PROFILE_DB_FILE)
            cursor = conn.cursor()
            query = f"SELECT {P_COL_UID} FROM {BUDDY_TABLE} WHERE {P_COL_QQ} = ?"
            result = cursor.execute(query, (identifier,)).fetchone()
            if result:
                return result[0]
            try:
                query_v6 = (
                    f"SELECT {P_COL_UID} FROM {PROFILE_TABLE} WHERE {P_COL_QQ} = ?"
                )
                result = cursor.execute(query_v6, (identifier,)).fetchone()
                if result:
                    return result[0]
            except sqlite3.OperationalError:
                pass
            return None
        except sqlite3.Error as e:
            print(f"通过QQ号查询UID时出错: {e}")
            return None
        finally:
            if "conn" in locals() and conn:
                conn.close()

    def set_my_uid(self, uid):
        self.my_uid = uid
        if uid not in self.friends and self.is_enabled:
            try:
                conn = sqlite3.connect(PROFILE_DB_FILE)
                query = f"SELECT {P_COL_UID}, {P_COL_QQ}, {P_COL_NAME}, {P_COL_REMARK} FROM {PROFILE_TABLE} WHERE {P_COL_UID} = ?"
                my_info = conn.cursor().execute(query, (uid,)).fetchone()
                if my_info:
                    self.friends[my_info[0]] = {
                        "qq": my_info[1],
                        "name": my_info[2],
                        "remark": my_info[3],
                    }
            finally:
                if "conn" in locals() and conn:
                    conn.close()

    def get_display_info(self, uid, format_str):
        if not self.is_enabled or not self.my_uid or not uid:
            return uid or "未知用户"

        if uid == self.my_uid:
            defaults = {"name": "我", "qq": "我的QQ"}
        else:
            defaults = {"name": f"未知用户({uid[-4:]})", "qq": "未知QQ"}

        info = self.friends.get(uid, {})
        name = info.get("name", defaults["name"])
        remark = info.get("remark")
        qq = info.get("qq", defaults["qq"])
        remark_or_name = remark or name

        return format_str.format(
            name=name,
            qq=qq,
            uid=uid,
            remark=remark or "",
            remark_or_name=remark_or_name,
        )

    def get_filename_part(self, uid):
        if not self.is_enabled:
            return uid
        info = self.friends.get(uid, {"qq": uid, "name": "Unknown", "remark": None})
        qq, name, remark = (
            info.get("qq", uid),
            info.get("name", "Unknown"),
            info.get("remark"),
        )
        return f"{qq}-{name}(备注-{remark})" if remark else f"{qq}-{name}"


def get_text_from_raw(raw_message, profile_manager, display_format):
    if not raw_message:
        return ""
    try:
        messages, typedef = blackboxprotobuf.decode_message(raw_message)
        single_messages = messages.get(PB_FIELD_MSG_CONTAINER, [])
        if not isinstance(single_messages, list):
            single_messages = [single_messages]

        text_parts = []
        for msg in single_messages:
            if not isinstance(msg, dict):
                continue

            def extract_text(sub_message):
                if not isinstance(sub_message, dict):
                    return

                if PB_FIELD_REPLY in sub_message:
                    original_sender_uid = sub_message.get("40020", b"").decode(
                        "utf-8", "ignore"
                    )
                    original_timestamp = sub_message.get("47404")

                    nested_reply_obj = sub_message[PB_FIELD_REPLY]
                    original_text = ""
                    if isinstance(nested_reply_obj, dict):
                        original_text = nested_reply_obj.get(PB_FIELD_TEXT, b"").decode(
                            "utf-8", "ignore"
                        )

                    if not original_text:
                        original_text = sub_message.get("47413", b"").decode(
                            "utf-8", "ignore"
                        )

                    original_sender_info = "未知用户"
                    if profile_manager and original_sender_uid:
                        original_sender_info = profile_manager.get_display_info(
                            original_sender_uid, display_format
                        )

                    time_str = "未知时间"
                    if original_timestamp:
                        time_str = datetime.fromtimestamp(original_timestamp).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                    text_parts.append(
                        f"\n    [回复-> [{time_str}] {original_sender_info}: {original_text} <-]"
                    )

                elif PB_FIELD_TEXT in sub_message:
                    text_parts.append(
                        sub_message[PB_FIELD_TEXT].decode("utf-8", errors="ignore")
                    )

                elif sub_message.get("45002") == 8 and "48214" in sub_message:
                    xml_text = sub_message.get("48214", b"").decode("utf-8", "ignore")
                    clean_text = re.sub(r"<[^>]+>", "", xml_text).strip()
                    text_parts.append(clean_text)

            extract_text(msg)

        return "".join(text_parts)
    except Exception:
        return ""


def get_user_config(profile_manager):
    """获取用户输入，确定导出模式和参数。"""
    print("\n" + "=" * 42)
    print("==      QQ 聊天记录导出工具       ==")
    print("=" * 42)
    while True:
        print("\n请选择导出模式:")
        print("  1. 全部导出 (按全局时间线排序)")
        print("  2. 全部导出 (按好友分类保存)")
        print("  3. 导出指定好友")
        mode = input("请输入模式编号 (1/2/3): ")
        if mode in ["1", "2", "3"]:
            break
        print("输入无效。")

    target_uid = None
    if mode == "3":
        if profile_manager.is_enabled:
            print("\n好友列表:")
            friend_list = sorted(
                profile_manager.friends.items(),
                key=lambda item: (
                    item[1].get("remark") or item[1].get("name") or "zzzz"
                ).lower(),
            )
            for i, (uid, info) in enumerate(friend_list):
                name, remark, qq = info.get("name"), info.get("remark"), info.get("qq")
                display_str = (
                    f"{remark} (昵称: {name}) (QQ: {qq})"
                    if remark
                    else f"{name} (QQ: {qq})"
                )
                print(f"  {i+1}: {display_str}")
            while True:
                try:
                    choice = int(input("请输入您想导出的好友的序号: "))
                    if 1 <= choice <= len(friend_list):
                        target_uid = friend_list[choice - 1][0]
                        break
                    else:
                        print("序号超出范围。")
                except ValueError:
                    print("请输入数字序号。")
        else:
            target_uid = input("请输入您想导出的好友的UID: ").strip()

    print("\n是否筛选时间范围? (不需要请直接按回车)")
    start_date_str = input("请输入开始日期 (格式YYYY-MM-DD): ").strip()
    end_date_str = input("请输入结束日期 (格式YYYY-MM-DD): ").strip()
    start_ts, end_ts = None, None
    try:
        if start_date_str:
            start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
        if end_date_str:
            end_ts = int(
                datetime.strptime(
                    end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S"
                ).timestamp()
            )
    except ValueError:
        print("提示: 日期格式错误，将不进行时间筛选。")
        start_ts, end_ts = None, None

    display_format = "{name}"
    if profile_manager.is_enabled:
        print("\n请选择用户标识显示格式:")
        print("  1. 昵称 (默认)")
        print("  2. 昵称/备注 (优先显示备注)")
        print("  3. QQ号码")
        print("  4. UID")
        print("  5. 自定义格式")
        format_choice = input("请输入格式编号 (1-5，默认1): ").strip()

        format_map = {"1": "{name}", "2": "{remark_or_name}", "3": "{qq}", "4": "{uid}"}

        if format_choice == "5":
            print("可用占位符: {name}, {remark}, {remark_or_name}, {qq}, {uid}")
            display_format = input("请输入自定义格式: ").strip() or "{name}"
        else:
            display_format = format_map.get(format_choice, "{name}")

    return {
        "mode": mode,
        "target_uid": target_uid,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "format": display_format,
    }


def fetch_data(config):
    """根据配置从数据库查询数据。"""
    try:
        conn = sqlite3.connect(C2C_DB_FILE)
        cursor = conn.cursor()
        print(f"\n聊天记录库 '{C2C_DB_FILE}' 打开成功。")
        params = []
        query = f"SELECT * FROM {C2C_TABLE} WHERE {C2C_COL_SENDER_UID} IS NOT NULL AND {C2C_COL_PEER_UID} IS NOT NULL AND {C2C_COL_MSG_TIME} IS NOT NULL"
        if config["target_uid"]:
            query += f" AND ({C2C_COL_SENDER_UID} = ? OR {C2C_COL_PEER_UID} = ?)"
            params.extend([config["target_uid"], config["target_uid"]])
        if config["start_ts"]:
            query += f" AND {C2C_COL_MSG_TIME} >= ?"
            params.append(config["start_ts"])
        if config["end_ts"]:
            query += f" AND {C2C_COL_MSG_TIME} <= ?"
            params.append(config["end_ts"])
        query += f" ORDER BY {C2C_COL_MSG_TIME} ASC;"
        print("正在查询和加载聊天记录...")
        cursor.execute(query, tuple(params))
        all_rows = cursor.fetchall()
        print(f"查询完成，找到 {len(all_rows)} 条相关记录。")
        return all_rows
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return None
    finally:
        if "conn" in locals() and conn:
            conn.close()


def sanitize_filename(name):
    """清理文件名中的非法字符。"""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _write_single_conversation(filename, records, profile_manager, display_format):
    """将单组对话记录写入指定文件。"""
    with open(filename, "w", encoding="utf-8") as f:
        for r in records:
            sender_str = profile_manager.get_display_info(r["sender"], display_format)
            time_str = datetime.fromtimestamp(r["time"]).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f'[{time_str}] {sender_str}: {r["text"]}\n')


def process_and_write(rows, config, profile_manager):
    """处理数据并根据模式写入文件。"""
    if not rows:
        print("没有可导出的记录。")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    my_uid, fmt = profile_manager.my_uid, config["format"]

    print("正在解析消息内容...")
    processed_records = []
    for row in rows:
        full_message = get_text_from_raw(row[17], profile_manager, fmt)
        if full_message.strip():
            processed_records.append(
                {
                    "sender": row[7],
                    "peer": row[9],
                    "time": row[13],
                    "text": full_message,
                }
            )

    print(f"解析完成，共 {len(processed_records)} 条有效消息。")
    if not processed_records:
        return

    if config["mode"] == "1":
        filename = os.path.join(OUTPUT_DIR, "chat_logs_timeline.txt")
        print(f"开始写入文件 '{filename}'...")
        with open(filename, "w", encoding="utf-8") as f:
            for r in processed_records:
                sender_str = profile_manager.get_display_info(r["sender"], fmt)
                time_str = datetime.fromtimestamp(r["time"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                f.write(f'[{time_str}] {sender_str}: {r["text"]}\n')
        print(f"导出完成。")

    elif config["mode"] == "2":
        output_dir_by_friend = os.path.join(OUTPUT_DIR, "chat_logs_by_friend")
        os.makedirs(output_dir_by_friend, exist_ok=True)
        print(f"开始分类写入文件夹 '{output_dir_by_friend}'...")
        conversations = {}
        for r in processed_records:
            friend_uid = r["peer"] if r["sender"] == my_uid else r["sender"]
            if friend_uid not in conversations:
                conversations[friend_uid] = []
            conversations[friend_uid].append(r)

        for friend_uid, records in conversations.items():
            filename_part = profile_manager.get_filename_part(friend_uid)
            filename = os.path.join(
                output_dir_by_friend, f"聊天记录-{sanitize_filename(filename_part)}.txt"
            )
            _write_single_conversation(filename, records, profile_manager, fmt)
        print(f"导出完成，共为 {len(conversations)} 位好友生成了文件。")

    elif config["mode"] == "3":
        filename_part = profile_manager.get_filename_part(config["target_uid"])
        filename = os.path.join(
            OUTPUT_DIR, f"聊天记录-{sanitize_filename(filename_part)}.txt"
        )
        print(f'开始写入文件 "{filename}"...')
        _write_single_conversation(filename, processed_records, profile_manager, fmt)
        print("导出完成。")


def main():
    """主函数。"""
    profile_manager = ProfileManager(PROFILE_DB_FILE)
    config = get_user_config(profile_manager)

    if profile_manager.is_enabled:
        identifier = input(
            "\n为正确解析对话和分类，请输入您自己的【UID】或【QQ号】: "
        ).strip()
        if identifier:
            my_uid = profile_manager.find_uid(identifier)
            if my_uid:
                print(f"-> 已识别用户 UID: {my_uid}")
                profile_manager.set_my_uid(my_uid)
            else:
                print(
                    f"-> 提示: 未能通过'{identifier}'找到有效UID。昵称/备注显示可能不完整或分类错误。"
                )
        else:
            print("提示: 未输入身份标识，昵称/备注显示可能不完整或分类错误。")

    rows = fetch_data(config)
    if rows:
        process_and_write(rows, config, profile_manager)
    print("\n导出任务已完成。")


if __name__ == "__main__":
    main()
