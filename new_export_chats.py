# -*- coding: utf-8 -*-

import sqlite3
import os
import base64
from datetime import datetime
import re
import json

# 尝试导入 blackboxprotobuf，这是一个无需.proto文件即可解析Protobuf的库
try:
    import blackboxprotobuf
except ImportError:
    print("错误：缺少 'blackboxprotobuf' 库。")
    print("请使用 'pip install blackboxprotobuf' 命令进行安装。")
    exit(1)

# --- 常量定义 ---

# 【用户配置】
# 用于在无法自动判断时，作为后备的用户UID缓存文件。
# 脚本会自动创建和读取此文件，无需手动配置。
UID_FILENAME = "myqq"

# 【文件与路径配置】
DB_FILENAME = "nt_msg.decrypt.db"
OUTPUT_DIR = "output_chats"
OUTPUT_FILENAME = "chat_logs_timeline.txt"

# 【数据库表结构常量】
# 基于QQ NT版数据库逆向工程得出的表名和列名，是脚本正确读取数据的关键
TABLE_NAME = "c2c_msg_table"
COL_SENDER_UID = "40020"
COL_PEER_UID = "40021"
COL_TIMESTAMP = "40050"
COL_MSG_CONTENT = "40800"

# 【Protobuf内部字段ID常量】
# 这些是Protobuf消息体内部各数据段的唯一标识符（Tag），同样基于逆向工程得出。
PB_MSG_CONTAINER = "40800"
PB_MSG_TYPE = "45002"
PB_MSG_SUBTYPE = "45003"
PB_TEXT_CONTENT = "45101"
PB_ARK_JSON = "47901"
PB_RECALLER_NAME = "47705"
PB_FILE_NAME = "45402"
PB_CALL_STATUS = "48153"
PB_CALL_TYPE = "48154"
PB_MARKET_FACE_TEXT = "80900"
PB_IMAGE_IS_FLASH = "45829"  # 图片是否为闪照的标志字段
PB_REDPACKET_TYPE = "48412"  # 红包类型字段 (2:普通, 6:口令)
PB_REDPACKET_TITLE = "48443"  # 红包标题
# --- 引用消息相关字段 ---
PB_REPLY_ORIGIN_SENDER_UID = "40020"
PB_REPLY_ORIGIN_RECEIVER_UID = "40021"
PB_REPLY_ORIGIN_TS = "47404"
PB_REPLY_ORIGIN_SUMMARY_TEXT = "47413"
PB_REPLY_ORIGIN_OBJ = "47423"
# --- 互动灰字提示相关字段 ---
PB_GRAYTIP_INTERACTIVE_XML = "48214"
# --- 普通灰字提示相关字段 ---
PB_GRAYTIP_TEXT = "48274"

# 消息元素类型ID -> 可读名称的映射
MSG_TYPE_MAP = {
    1: "文本",
    2: "图片",
    3: "文件",
    4: "语音",
    5: "视频",
    6: "QQ表情",
    7: "引用",
    8: "灰字提示",
    9: "红包",
    10: "卡片",
    11: "商城表情",
    14: "Markdown",
    21: "通话",
}

# 【过滤规则】
# 定义需要被忽略的系统提示的正则表达式列表
IGNORE_GRAY_TIP_PATTERNS_RAW = [
    r"^你已对此会话开启消息免打扰$",
    r"^自定义撤回消息",
    r"由于.*未互发消息",
    r"你们超过.*未互发消息",
    r"你们的.*即将彻底消失",
]
# 在脚本开始时预先编译正则表达式，可以显著提升后续循环匹配的性能
IGNORE_GRAY_TIP_PATTERNS = [re.compile(p) for p in IGNORE_GRAY_TIP_PATTERNS_RAW]


def get_my_uid():
    """
    【核心功能】自动检测或提示输入用户UID。
    该函数实现了UID的持久化，优先从本地文件读取，失败则引导用户输入，并提供保存选项。
    """
    if os.path.exists(UID_FILENAME):
        try:
            with open(UID_FILENAME, "r", encoding="utf-8") as f:
                uid = f.read().strip()
            if uid and uid.startswith("u_"):
                print(f"\n成功从 '{UID_FILENAME}' 文件中加载您的UID: {uid}")
                return uid
        except IOError:
            pass
    while True:
        raw_input_str = input(
            "\n>> 请输入您的UID (通常以 u_ 开头)。\n   输入 -save 后缀可保存UID供下次使用 (例如: u_xxxx-save): "
        ).strip()
        save_uid = raw_input_str.lower().endswith("-save")
        uid = (
            re.sub(r"[\s-]*save$", "", raw_input_str, flags=re.IGNORECASE).strip()
            if save_uid
            else raw_input_str
        )
        if uid and uid.startswith("u_"):
            if save_uid:
                try:
                    with open(UID_FILENAME, "w", encoding="utf-8") as f:
                        f.write(uid)
                    print(f"-> UID已成功保存到 '{UID_FILENAME}' 文件中。")
                except IOError as e:
                    print(f"-> 错误：无法保存UID文件。{e}")
            return uid
        else:
            print("   输入的UID格式似乎不正确，请重新输入。")


def get_placeholder(value, placeholder="N/A"):
    """处理空值或"0"，返回占位符"""
    return value if value and str(value) != "0" else placeholder


def format_timestamp(ts):
    """将时间戳格式化为易读的日期时间字符串"""
    if isinstance(ts, int) and ts > 0:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return f"时间戳({ts})"
    return "N/A"


def _extract_readable_text(data: bytes) -> str or None:
    """
    【核心抢救逻辑】当标准Protobuf解码失败时，调用此函数尝试从原始字节流中强行提取可读的文本片段。
    这是您改进后的版本，它通过一个宽泛的正则表达式来寻找最长的可能消息内容。
    """
    if not data:
        return None
    try:
        decoded_str = data.decode("utf-8", errors="replace")
        readable_pattern = (
            r"[a-zA-Z0-9\u4e00-\u9fa5\s.,!?;:\'\"()\[\]{}_\-+=*/\\|<>@#$%^&~]+"
        )
        all_fragments = re.findall(readable_pattern, decoded_str)
        if not all_fragments:
            return None
        longest_fragment = max(all_fragments, key=len)
        return longest_fragment.strip()
    except Exception:
        return None


def _parse_single_segment(segment: dict) -> str:
    """内部辅助函数，为引用消息提供原文的文本摘要。"""
    if not isinstance(segment, dict):
        return ""
    msg_type = segment.get(PB_MSG_TYPE)
    # 动画表情的子类型为1，以此与普通图片区分
    if msg_type == 2 and segment.get(PB_MSG_SUBTYPE) == 1:
        return "[动画表情]"
    # 【新增】区分闪照和普通图片
    if msg_type == 2:
        return "[闪照]" if segment.get(PB_IMAGE_IS_FLASH) == 1 else "[图片]"
    # 【新增】区分红包类型
    if msg_type == 9:
        title = (
            segment.get("48403", {})
            .get(PB_REDPACKET_TITLE, b"")
            .decode("utf-8", "ignore")
        )
        if segment.get(PB_REDPACKET_TYPE) == 6:
            return f"[口令红包] {title}"
        return f"[红包] {title}"
    if msg_type == 11 and PB_MARKET_FACE_TEXT in segment:
        return segment[PB_MARKET_FACE_TEXT].decode("utf-8", "ignore")
    if PB_TEXT_CONTENT in segment:
        return segment.get(PB_TEXT_CONTENT, b"").decode("utf-8", "ignore")
    if msg_type == 5:
        return "[视频]"
    return f"[{MSG_TYPE_MAP.get(msg_type, '消息')}]"


def _decode_interactive_gray_tip(segment: dict) -> dict or None:
    """解析互动式灰字提示（如戳一戳、拍一拍），返回结构化字典用于后续特殊格式化。"""
    try:
        xml_text = segment.get(PB_GRAYTIP_INTERACTIVE_XML, b"").decode(
            "utf-8", "ignore"
        )
        uids = re.findall(r'<qq uin="([^"]+)"', xml_text)
        texts = re.findall(r'<nor txt="([^"]*)"', xml_text)
        if len(uids) >= 2 and len(texts) >= 1:
            return {
                "type": "interactive_tip",
                "actor": uids[0],
                "target": uids[1],
                "verb": texts[0] or "戳了戳",
                "suffix": texts[1] if len(texts) > 1 else "",
            }
    except Exception:
        return None
    return None


def decode_gray_tip(segment: dict) -> dict or str or None:
    """解析灰字提示（类型8），根据内容返回不同类型的结果，或None以过滤消息。"""
    interactive_tip_data = _decode_interactive_gray_tip(segment)
    if interactive_tip_data:
        return interactive_tip_data
    if PB_RECALLER_NAME in segment:
        recaller = segment[PB_RECALLER_NAME].decode("utf-8", "ignore")
        return f"[{recaller} 撤回了一条消息]"
    text = segment.get(PB_GRAYTIP_TEXT, b"").decode("utf-8", "ignore")
    if text:
        for pattern in IGNORE_GRAY_TIP_PATTERNS:
            if pattern.search(text):
                return None
        return f"[{text}]"
    return "[系统提示]"


def decode_ark_message(segment: dict) -> str or None:
    """解析并过滤Ark卡片消息，只保留需要的类型。"""
    try:
        ark_json_str = segment.get(PB_ARK_JSON)
        if not ark_json_str:
            return None
        ark_data = json.loads(
            ark_json_str.decode("utf-8", "ignore")
            if isinstance(ark_json_str, bytes)
            else ark_json_str
        )
        app, prompt = ark_data.get("app"), ark_data.get("prompt", "")
        if app == "com.tencent.contact.lua" and "推荐联系人" in prompt:
            return f"[名片] {prompt}"
        if app == "com.tencent.miniapp_01" and "[QQ小程序]" in prompt:
            return prompt
        if app == "com.tencent.multimsg":
            source = (
                ark_data.get("meta", {}).get("detail", {}).get("source", "未知来源")
            )
            summary = (
                ark_data.get("meta", {})
                .get("detail", {})
                .get("summary", "查看转发消息")
            )
            return f"[聊天记录] {source}: {summary}"
        return None
    except Exception:
        return "[卡片-解析失败]"


def decode_message_content(content_bytes: bytes) -> list or None:
    """【核心消息解析函数】负责将原始字节流解码为可读的消息部分列表。"""
    if not content_bytes:
        return None
    try:
        decoded_outer, _ = blackboxprotobuf.decode_message(content_bytes)
        segments_data = decoded_outer.get(PB_MSG_CONTAINER)
        if segments_data is None:
            return ["[结构错误: 未找到消息容器]"]
        segments = segments_data if isinstance(segments_data, list) else [segments_data]
        message_parts = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            msg_type = segment.get(PB_MSG_TYPE)
            part_to_add = None
            if msg_type not in MSG_TYPE_MAP:
                continue

            # --- 消息类型分发器 ---
            if msg_type == 1:
                part_to_add = segment.get(PB_TEXT_CONTENT, b"").decode(
                    "utf-8", "ignore"
                )
            elif msg_type == 7:
                origin_content = segment.get(PB_REPLY_ORIGIN_SUMMARY_TEXT, b"").decode(
                    "utf-8", "ignore"
                )
                if not origin_content:
                    origin_obj = segment.get(PB_REPLY_ORIGIN_OBJ)
                    origin_content = (
                        _parse_single_segment(origin_obj) if origin_obj else ""
                    )
                sender = get_placeholder(
                    segment.get(PB_REPLY_ORIGIN_SENDER_UID, b"").decode("utf-8")
                )
                receiver = get_placeholder(
                    segment.get(PB_REPLY_ORIGIN_RECEIVER_UID, b"").decode("utf-8")
                )
                ts = format_timestamp(segment.get(PB_REPLY_ORIGIN_TS))
                part_to_add = (
                    f"[引用-> [{ts}] {sender} -> {receiver}: {origin_content} <-]"
                )
            elif msg_type == 21:
                status_text = segment.get(PB_CALL_STATUS, b"").decode("utf-8", "ignore")
                call_type_code = segment.get(PB_CALL_TYPE)
                call_type_str = (
                    "语音通话"
                    if call_type_code == 1
                    else "视频通话" if call_type_code == 2 else "通话"
                )
                part_to_add = f"[{call_type_str}] {status_text}"
            elif msg_type == 8:
                part_to_add = decode_gray_tip(segment)
            elif msg_type == 10:
                part_to_add = decode_ark_message(segment)
            else:
                part_to_add = _parse_single_segment(segment)

            if part_to_add:
                message_parts.append(part_to_add)
        return message_parts if message_parts else None

    except Exception:
        # 【内容抢救机制】
        try:
            temp_str = content_bytes.decode("utf-8", "ignore")
            match = re.search(r"(\[[^\]]{1,10}\])", temp_str)
            if match:
                return [match.group(1)]
        except Exception:
            pass
        readable_text = _extract_readable_text(content_bytes)
        if readable_text:
            return [readable_text]
        return [f"[解码失败-BASE64] {base64.b64encode(content_bytes).decode('ascii')}"]


def main():
    """主执行函数，负责流程控制"""
    print("--- QQ聊天记录导出工具 (v10 - 精细区分版) ---")
    MY_UID = get_my_uid()
    print(f"\n目标数据库: {DB_FILENAME}")
    if not os.path.exists(DB_FILENAME):
        print(f"错误: 数据库文件 '{DB_FILENAME}' 不存在。")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)

    try:
        con = sqlite3.connect(f"file:{DB_FILENAME}?mode=ro", uri=True)
        cur = con.cursor()
        query = f"SELECT `{COL_TIMESTAMP}`, `{COL_SENDER_UID}`, `{COL_PEER_UID}`, `{COL_MSG_CONTENT}` FROM {TABLE_NAME} ORDER BY `{COL_TIMESTAMP}` ASC"
        print("\n正在查询数据库 (使用UID)...")
        cur.execute(query)
        rows = cur.fetchall()
        if not rows:
            print("\n查询完成，但未能获取任何记录。")
            return

        print(f"查询完成，共 {len(rows)} 行原始记录。")
        print("开始精细化解析并写入文件...")
        processed_count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for row in rows:
                raw_ts, sender_uid, peer_uid, content = row
                message_parts = decode_message_content(content)

                if not message_parts:
                    continue

                message_text_joined = " ".join(
                    str(p) for p in message_parts if not isinstance(p, dict)
                )
                if message_text_joined == "[系统提示]":
                    continue

                formatted_time = format_timestamp(raw_ts)
                first_part = message_parts[0]

                if (
                    isinstance(first_part, dict)
                    and first_part.get("type") == "interactive_tip"
                ):
                    tip = first_part
                    message_body = (
                        f"{tip['actor']} {tip['verb']} {tip['target']}{tip['suffix']}"
                    )
                    output_line = f"[{formatted_time}] [系统提示]: {message_body}\n"
                else:
                    sender_placeholder = get_placeholder(sender_uid)
                    receiver_placeholder = get_placeholder(peer_uid)
                    if sender_placeholder == receiver_placeholder:
                        peer_uid = MY_UID
                    sender_display = get_placeholder(sender_uid)
                    receiver_display = get_placeholder(peer_uid)
                    if sender_display == "N/A":
                        sender_display = "[系统提示]"
                    output_line = f"[{formatted_time}] {sender_display} -> {receiver_display}: {message_text_joined}\n"

                f.write(output_line)
                processed_count += 1

        print(f"\n处理完成！共导出 {processed_count} 条有效消息。")
        print(f"（注意：部分无意义的系统提示、未知类型及部分卡片消息已被规则过滤）")
        print(f"结果已保存到: {output_path}")
    except sqlite3.Error as e:
        print(f"\n数据库错误: {e}")
    except Exception as e:
        print(f"\n发生未知错误: {e}")
    finally:
        if "con" in locals() and con:
            con.close()


if __name__ == "__main__":
    main()
