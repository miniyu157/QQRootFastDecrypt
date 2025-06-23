# -*- coding: utf-8 -*-

import sqlite3
import os
import base64
from datetime import datetime
import re
import json

# 尝试导入 blackboxprotobuf
try:
    import blackboxprotobuf
except ImportError:
    print("错误：缺少 'blackboxprotobuf' 库。")
    print("请使用 'pip install blackboxprotobuf' 命令进行安装。")
    exit(1)

# --- 常量定义 ---

# 文件和路径
DB_FILENAME = "nt_msg.decrypt.db"
OUTPUT_DIR = "output_chats"
OUTPUT_FILENAME = "chat_logs_timeline.txt"
UID_FILENAME = "myqq"  # 保存用户UID的文件名

# 数据库表和列
TABLE_NAME = "c2c_msg_table"
COL_SENDER_UID = "40020"
COL_PEER_UID = "40021"
COL_TIMESTAMP = "40050"
COL_MSG_CONTENT = "40800"

# Protobuf 内部字段ID
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
# 引用消息相关字段
PB_REPLY_ORIGIN_SENDER_UID = "40020"
PB_REPLY_ORIGIN_RECEIVER_UID = "40021"
PB_REPLY_ORIGIN_TS = "47404"
PB_REPLY_ORIGIN_SUMMARY_TEXT = "47413"
PB_REPLY_ORIGIN_OBJ = "47423"
# 互动灰字提示相关字段
PB_GRAYTIP_INTERACTIVE_USERS = "48210"
PB_GRAYTIP_INTERACTIVE_XML = "48214"
# 普通灰字提示相关字段
PB_GRAYTIP_TEXT = "48274"

# 消息元素类型说明
MSG_TYPE_MAP = {
    1: "文本", 2: "图片", 3: "文件", 4: "语音", 5: "视频",
    6: "QQ表情", 7: "引用", 8: "灰字提示", 9: "红包", 10: "卡片",
    11: "商城表情", 14: "Markdown", 21: "通话",
}
IGNORE_GRAY_TIPS = ["你已对此会话开启消息免打扰", "自定义撤回消息，有趣化解尴尬。"]

def get_my_uid():
    """【新增】自动检测或提示输入用户UID"""
    if os.path.exists(UID_FILENAME):
        try:
            with open(UID_FILENAME, 'r', encoding='utf-8') as f:
                uid = f.read().strip()
            if uid and uid.startswith('u_'):
                print(f"\n成功从 '{UID_FILENAME}' 文件中加载您的UID: {uid}")
                return uid
            else:
                print(f"警告: '{UID_FILENAME}' 文件内容无效，将提示您手动输入。")
        except IOError as e:
            print(f"警告: 读取 '{UID_FILENAME}' 文件失败 ({e})，将提示您手动输入。")

    # 文件不存在或无效，提示用户输入
    while True:
        raw_input_str = input("\n>> 请输入您的UID (通常以 u_ 开头)。\n   输入 -save 后缀可保存UID供下次使用 (例如: u_xxxx-save): ").strip()
        
        save_uid = False
        if raw_input_str.lower().endswith('-save'):
            save_uid = True
            # 从输入中剥离 '-save' 后缀及前后空格
            uid = re.sub(r'[\s-]*save$', '', raw_input_str, flags=re.IGNORECASE).strip()
        else:
            uid = raw_input_str

        if uid and uid.startswith('u_'):
            if save_uid:
                try:
                    with open(UID_FILENAME, 'w', encoding='utf-8') as f:
                        f.write(uid)
                    print(f"-> UID已成功保存到 '{UID_FILENAME}' 文件中。")
                except IOError as e:
                    print(f"-> 错误：无法保存UID文件。{e}")
            return uid
        else:
            print("   输入的UID格式似乎不正确，请重新输入。")

def get_placeholder(value, placeholder="N/A"):
    return value if value and str(value) != "0" else placeholder

def format_timestamp(ts):
    if isinstance(ts, int) and ts > 0:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return f"时间戳({ts})"
    return "N/A"

def _parse_single_segment(segment: dict) -> str:
    if not isinstance(segment, dict): return ""
    msg_type = segment.get(PB_MSG_TYPE)
    if msg_type == 2 and segment.get(PB_MSG_SUBTYPE) == 1: return "[动画表情]"
    if msg_type == 11 and PB_MARKET_FACE_TEXT in segment:
        return segment[PB_MARKET_FACE_TEXT].decode("utf-8", "ignore")
    if PB_TEXT_CONTENT in segment:
        return segment.get(PB_TEXT_CONTENT, b"").decode("utf-8", "ignore")
    if msg_type == 2: return "[图片]"
    if msg_type == 5: return "[视频]"
    if msg_type == 9: return "[红包]"
    return f"[{MSG_TYPE_MAP.get(msg_type, '消息')}]"

def _decode_interactive_gray_tip(segment: dict) -> str or None:
    try:
        nick_list = segment.get(PB_GRAYTIP_INTERACTIVE_USERS, [])
        nick_map = {item.get("1005").decode("utf-8", "ignore"): item.get("1006", b"").decode("utf-8", "ignore") for item in nick_list if "1005" in item}
        xml_text = segment.get(PB_GRAYTIP_INTERACTIVE_XML, b"").decode("utf-8", "ignore")
        uids = re.findall(r'<qq uin="([^"]+)"', xml_text)
        texts = re.findall(r'<nor txt="([^"]*)"', xml_text)
        if len(uids) >= 2 and len(texts) >= 1:
            actor_uid, target_uid = uids[0], uids[1]
            actor_name, target_name = nick_map.get(actor_uid, actor_uid), nick_map.get(target_uid, target_uid)
            verb = texts[0]
            suffix = texts[1] if len(texts) > 1 else ""
            return f"[{actor_name} {verb} {target_name}{suffix}]"
    except Exception: return None
    return None

def decode_gray_tip(segment: dict) -> str or None:
    interactive_tip = _decode_interactive_gray_tip(segment)
    if interactive_tip: return interactive_tip
    if PB_RECALLER_NAME in segment:
        recaller = segment[PB_RECALLER_NAME].decode("utf-8", "ignore")
        return f"[{recaller} 撤回了一条消息]"
    text = segment.get(PB_GRAYTIP_TEXT, b"").decode("utf-8", "ignore")
    if text:
        if text in IGNORE_GRAY_TIPS: return None
        return f"[{text}]"
    return "[系统提示]"

def decode_ark_message(segment: dict) -> str or None:
    try:
        ark_json_str = segment.get(PB_ARK_JSON)
        if not ark_json_str: return None
        ark_data = json.loads(ark_json_str.decode("utf-8", "ignore") if isinstance(ark_json_str, bytes) else ark_json_str)
        app = ark_data.get("app")
        prompt = ark_data.get("prompt", "")
        if app == "com.tencent.contact.lua" and "推荐联系人" in prompt: return f"[名片] {prompt}"
        if app == "com.tencent.miniapp_01" and "[QQ小程序]" in prompt: return prompt
        if app == "com.tencent.multimsg":
            source = ark_data.get("meta", {}).get("detail", {}).get("source", "未知来源")
            summary = ark_data.get("meta", {}).get("detail", {}).get("summary", "查看转发消息")
            return f"[聊天记录] {source}: {summary}"
        return None
    except Exception: return "[卡片-解析失败]"

def decode_message_content(content_bytes: bytes) -> str or None:
    if not content_bytes: return None
    try:
        decoded_outer, _ = blackboxprotobuf.decode_message(content_bytes)
        segments_data = decoded_outer.get(PB_MSG_CONTAINER)
        if segments_data is None: return "[结构错误: 未找到消息容器]"
        segments = segments_data if isinstance(segments_data, list) else [segments_data]
        message_parts = []
        for segment in segments:
            if not isinstance(segment, dict): continue
            msg_type = segment.get(PB_MSG_TYPE)
            part_to_add = None
            if msg_type not in MSG_TYPE_MAP: continue
            
            if msg_type == 1: part_to_add = segment.get(PB_TEXT_CONTENT, b"").decode("utf-8", "ignore")
            elif msg_type == 7:
                origin_content = segment.get(PB_REPLY_ORIGIN_SUMMARY_TEXT, b'').decode('utf-8', 'ignore')
                if not origin_content:
                    origin_obj = segment.get(PB_REPLY_ORIGIN_OBJ)
                    origin_content = _parse_single_segment(origin_obj) if origin_obj else ""
                sender = get_placeholder(segment.get(PB_REPLY_ORIGIN_SENDER_UID, b'').decode('utf-8'))
                receiver = get_placeholder(segment.get(PB_REPLY_ORIGIN_RECEIVER_UID, b'').decode('utf-8'))
                ts = format_timestamp(segment.get(PB_REPLY_ORIGIN_TS))
                part_to_add = f"[引用-> [{ts}] {sender} -> {receiver}: {origin_content} <-]"
            elif msg_type == 21:
                status_text = segment.get(PB_CALL_STATUS, b"").decode("utf-8", "ignore")
                call_type_code = segment.get(PB_CALL_TYPE)
                call_type_str = "语音通话" if call_type_code == 1 else "视频通话" if call_type_code == 2 else "通话"
                part_to_add = f"[{call_type_str}] {status_text}"
            elif msg_type == 8: part_to_add = decode_gray_tip(segment)
            elif msg_type == 10: part_to_add = decode_ark_message(segment)
            else: part_to_add = _parse_single_segment(segment)
            
            if part_to_add: message_parts.append(part_to_add)
        return " ".join(message_parts).strip() if message_parts else None
    except Exception:
        try: return f"[文本内容] {content_bytes.decode('utf-8')}"
        except UnicodeDecodeError: return f"[解码失败-BASE64] {base64.b64encode(content_bytes).decode('ascii')}"

def main():
    print("--- QQ聊天记录导出工具 (自动UID配置版) ---")
    
    # 【新增】获取用户UID
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
                message_text = decode_message_content(content)
                if message_text:
                    formatted_time = format_timestamp(raw_ts)
                    
                    sender_placeholder = get_placeholder(sender_uid)
                    receiver_placeholder = get_placeholder(peer_uid)
                    
                    # 您的自定义逻辑
                    if sender_placeholder == receiver_placeholder:
                        peer_uid = MY_UID
                    
                    sender_display = get_placeholder(sender_uid)
                    receiver_display = get_placeholder(peer_uid)
                    
                    # 系统提示美化
                    if sender_display == 'N/A':
                        sender_display = '[系统提示]'

                    output_line = f"[{formatted_time}] {sender_display} -> {receiver_display}: {message_text}\n"
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