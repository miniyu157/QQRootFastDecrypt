# -*- coding: utf-8 -*-
"""
QQ NT 聊天记录导出工具

功能:
- 自动从数据库识别主人身份及好友、分组信息。
- 支持多种导出模式: 全局时间线、全部好友、按分组、指定好友。
- 支持导出详细的用户信息列表。
- 支持自定义时间范围筛选。
- 支持自定义导出的用户标识格式。
- 自动处理多种消息类型，包括文本、图片、引用、红包、系统提示等。
- 对无法标准解析的消息提供“内容抢救”机制。

依赖:
- blackboxprotobuf: 用于解析QQ使用的Protobuf二进制数据格式。
"""

import sqlite3
import os
import base64
from datetime import datetime
import re
import json
import argparse
import warnings

# 忽略 google.protobuf 的 pkg_resources DEPRECATED 警告
# 这是 protobuf 库的一个已知问题，与本脚本功能无关
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')


# 尝试导入 blackboxprotobuf
try:
    import blackboxprotobuf
except ImportError:
    print("错误：缺少 'blackboxprotobuf' 库。")
    print("请使用 'pip install blackboxprotobuf' 命令进行安装。")
    exit(1)

# --- 常量定义 ---

# 【文件与路径配置】 - 这些是基础文件名，完整路径将在main函数中构建
_DB_FILENAME = "nt_msg.decrypt.db"  # 解密后的QQ聊天记录数据库文件名
_PROFILE_DB_FILENAME = "profile_info.decrypt.db"  # 主人信息及好友列表数据库
_OUTPUT_DIR_NAME = "output_chats"  # 导出文件的存放文件夹
_CONFIG_FILENAME = "export_config.json" # 导出配置
_TIMELINE_FILENAME_BASE = "chat_logs_timeline" # 全局时间线文件名前缀
_FRIENDS_LIST_FILENAME = "friends_list.txt" # 好友信息列表文件名
_ALL_USERS_LIST_FILENAME = "all_cached_users_list.txt" # 全部用户信息列表文件名

# 【动态路径变量】 - 将在main函数中根据命令行参数设置
DB_PATH = ""
PROFILE_DB_PATH = ""
OUTPUT_DIR = ""
CONFIG_PATH = ""


# 【核心数据结构缓存】
SALVAGE_CACHE = {}
MESSAGE_CONTENT_CACHE = {} # 用于缓存已处理消息的最终文本内容，解决引用信息不完整问题

# 【数据库表结构与字段常量】
# 这些常量基于对QQ NT版数据库的逆向工程得出，是脚本正确读取数据的关键。

# -- 消息数据库 (nt_msg.decrypt.db) --
TABLE_NAME = "c2c_msg_table"      # C2C（Client to Client）单聊消息表
COL_SENDER_UID = "40020"         # 发送者UID (字符串，如 u_xxxxxxxx)
COL_PEER_UID = "40021"           # 【关键】对话对方的UID，作为会话的唯一标识
COL_TIMESTAMP = "40050"          # 消息时间戳 (秒)
COL_MSG_CONTENT = "40800"        # 消息内容 (Protobuf格式的二进制数据)

# -- 用户信息数据库 (profile_info.decrypt.db) --
CATEGORY_LIST_TABLE = "category_list_v2" # 存储分组信息和主人UID的表
BUDDY_LIST_TABLE = "buddy_list"         # 【关键】好友列表，是判断好友关系的唯一依据
PROFILE_INFO_TABLE = "profile_info_v6"   # 包含所有用户（好友、非好友）详细信息的缓存表
# 列名
PROF_COL_UID = "1000"           # 用户UID
PROF_COL_QID = "1001"           # 用户QID (可能为null)
PROF_COL_QQ = "1002"            # 用户QQ号
PROF_COL_GROUP_ID = "25007"     # 用户所属分组ID
PROF_COL_GROUP_LIST_PB = "25011" # 存储分组列表的Protobuf字段
PROF_COL_NICKNAME = "20002"     # 用户昵称
PROF_COL_REMARK = "20009"       # 用户备注 (由主人设置)
PROF_COL_SIGNATURE = "20011"    # 个性签名

# -- Protobuf内部字段ID常量 --
# 分组信息Protobuf
PB_GROUP_ID = "25007"           # 分组ID
PB_GROUP_NAME = "25008"         # 分组名称
# 消息内容Protobuf
PB_MSG_CONTAINER = "40800"      # 消息段的容器字段，大部分消息内容都包裹在此字段内
PB_MSG_TYPE = "45002"           # 消息元素的类型ID (例如 1=文本, 2=图片)
PB_MSG_SUBTYPE = "45003"        # 消息元素的子类型ID (如区分图片和动画表情)
PB_EMOJI_DESC = "47602"         # QQ表情的文本描述 (如 /捂脸)
PB_TEXT_CONTENT = "45101"       # 文本/链接/Email等内容
PB_ARK_JSON = "47901"           # Ark卡片消息 (其内容通常为JSON格式的字符串)
PB_RECALLER_NAME = "47705"      # 撤回消息者的昵称 (不可靠，仅作后备)
PB_RECALLER_UID = "47703"       # 【关键】撤回消息者的UID
PB_RECALL_SUFFIX = "47713"      # 撤回消息的后缀文本 (例如 "你猜猜撤回了什么。")
PB_FILE_NAME = "45402"          # 文件名
PB_CALL_STATUS = "48153"        # 音视频通话状态文本 (如 "通话时长 00:10")
PB_CALL_TYPE = "48154"          # 通话类型 (1:语音, 2:视频)
PB_MARKET_FACE_TEXT = "80900"   # 商城表情文本 (如 "[贴贴]")
PB_IMAGE_IS_FLASH = "45829"     # 图片是否为闪照的标志字段 (1:是闪照)
PB_REDPACKET_TYPE = "48412"     # 红包类型字段 (2:普通, 6:口令, 15:语音红包)
PB_REDPACKET_TITLE = "48443"    # 红包标题 (如 "恭喜发财")
PB_VOICE_DURATION = "45005"     # 语音消息时长字段 (此为推测值，可能不准)
PB_VOICE_TO_TEXT = "45923"      # 语音转文字的结果文本
# 引用消息相关字段
PB_REPLY_ORIGIN_SENDER_UID = "40020"    # 引用消息中，原消息的发送者UID
PB_REPLY_ORIGIN_RECEIVER_UID = "40021"  # 引用消息中，原消息的接收者UID
PB_REPLY_ORIGIN_TS = "47404"            # 引用消息中，原消息的时间戳
PB_REPLY_ORIGIN_SUMMARY_TEXT = "47413"  # 【关键】原消息的文本摘要，用于快速显示引用内容
PB_REPLY_ORIGIN_OBJ = "47423"           # 引用消息中，完整的原消息对象
# 互动灰字提示相关字段
PB_GRAYTIP_INTERACTIVE_XML = "48214" # 互动类提示的XML内容 (如 "拍一拍")

# 消息元素类型ID -> 可读名称的映射
MSG_TYPE_MAP = {
    1: "文本", 2: "图片", 3: "文件", 4: "语音", 5: "视频",
    6: "QQ表情", 7: "引用", 8: "灰字提示", 9: "红包", 10: "卡片",
    11: "商城表情", 14: "Markdown", 21: "通话",
}

class ConfigManager:
    """负责加载、管理和保存在 `export_config.json` 中的导出配置。"""
    def __init__(self, config_path):
        self.config_path = config_path
        self.default_config = {
            'show_recall': True,
            'show_recall_suffix': True,
            'show_poke': True,
            'show_voice_to_text': True,
            'export_markdown': True,
        }
        self.config = self.load_config()

    def load_config(self):
        """加载JSON配置文件，如果文件不存在或格式错误，则使用默认配置。"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                config = self.default_config.copy()
                config.update(loaded_config)
                return config
            except (json.JSONDecodeError, TypeError):
                print(f"警告: 配置文件 '{self.config_path}' 格式错误，将使用默认配置。")
        return self.default_config

    def save_config(self):
        """将当前配置保存到JSON文件。"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
            print("配置已保存。")
        except IOError as e:
            print(f"错误: 无法保存配置文件到 '{self.config_path}'。 {e}")
            
class ProfileManager:
    """
    负责从profile_info.decrypt.db加载和管理所有用户、好友和分组信息。
    这是整个脚本的数据中枢，为其他所有功能提供用户信息支持。
    """
    def __init__(self, db_path):
        if not os.path.exists(db_path):
            print(f"错误: 身份数据库文件 '{db_path}' 不存在。")
            exit(1)
        self.db_path = f"file:{db_path}?mode=ro"
        self.my_uid = ""
        self.user_info = {}   # {uid: {qq, nickname, remark, group_id, ...}} 好友信息
        self.group_info = {}  # {group_id: group_name} 分组信息
        self.all_profiles_cache = {} # {uid: {qq, nickname, ...}} 所有缓存过的用户信息

    def load_data(self):
        """
        加载所有用户信息的总入口。
        严格遵循 buddy_list 作为好友关系的唯一来源。
        """
        print(f"\n正在从 '{os.path.basename(self.db_path.replace('file:', '').split('?')[0])}' 加载用户信息...")
        try:
            with sqlite3.connect(self.db_path, uri=True) as con:
                cur = con.cursor()
                self._load_my_uid(cur)
                self._load_groups(cur)
                self._load_all_profiles_cache(cur)
                self._build_friend_list()
                if self.my_uid in self.all_profiles_cache:
                    self.user_info[self.my_uid] = self.all_profiles_cache[self.my_uid]
                
                print("用户信息加载完毕。")
        except sqlite3.Error as e:
            print(f"\n读取身份数据库时发生错误: {e}")
            exit(1)

    def _load_my_uid(self, cur):
        """从category_list_v2表获取主人UID。"""
        cur.execute(f'SELECT "{PROF_COL_UID}" FROM {CATEGORY_LIST_TABLE} LIMIT 1')
        result = cur.fetchone()
        if not result or not result[0]:
            print(f"错误: 无法在 '{CATEGORY_LIST_TABLE}' 表中找到主人UID。")
            exit(1)
        self.my_uid = result[0]
        print(f"成功识别主人UID: {self.my_uid}")

    def _load_groups(self, cur):
        """解析Protobuf数据，建立分组ID和分组名称的映射。"""
        cur.execute(f'SELECT "{PROF_COL_GROUP_LIST_PB}" FROM {CATEGORY_LIST_TABLE} LIMIT 1')
        pb_data = cur.fetchone()
        if not pb_data or not pb_data[0]: return

        decoded, _ = blackboxprotobuf.decode_message(pb_data[0])
        group_list_data = decoded.get(PROF_COL_GROUP_LIST_PB)
        if not group_list_data: return
        
        groups = group_list_data if isinstance(group_list_data, list) else [group_list_data]
        for group in groups:
            group_id = group.get(PB_GROUP_ID)
            group_name = group.get(PB_GROUP_NAME, b'').decode('utf-8', 'ignore')
            if group_id is not None and group_name:
                self.group_info[group_id] = group_name

    def _load_all_profiles_cache(self, cur):
        """将profile_info_v6表的内容全部加载到字典，作为信息缓存。"""
        query = f'SELECT "{PROF_COL_UID}", "{PROF_COL_QQ}", "{PROF_COL_NICKNAME}", "{PROF_COL_REMARK}", "{PROF_COL_QID}", "{PROF_COL_SIGNATURE}" FROM {PROFILE_INFO_TABLE}'
        cur.execute(query)
        for uid, qq, nickname, remark, qid, signature in cur.fetchall():
            self.all_profiles_cache[uid] = {
                'qq': qq or uid, 'nickname': nickname or '', 'remark': remark or '', 
                'qid': qid or '', 'signature': signature or '', 'group_id': -1
            }

    def _build_friend_list(self):
        """以buddy_list为准，从all_profiles_cache中填充好友的详细信息。"""
        with sqlite3.connect(self.db_path, uri=True) as con:
            cur = con.cursor()
            self.user_info = {}
            query = f'SELECT "{PROF_COL_UID}", "{PROF_COL_QQ}", "{PROF_COL_GROUP_ID}" FROM {BUDDY_LIST_TABLE}'
            cur.execute(query)
            for friend_uid, friend_qq, friend_group_id in cur.fetchall():
                profile_details = self.all_profiles_cache.get(friend_uid, {})
                self.user_info[friend_uid] = {
                    'qq': friend_qq or profile_details.get('qq', friend_uid),
                    'nickname': profile_details.get('nickname', ''),
                    'remark': profile_details.get('remark', ''),
                    'qid': profile_details.get('qid', ''),
                    'signature': profile_details.get('signature', ''),
                    'group_id': friend_group_id if friend_group_id is not None else 0
                }

    def get_display_name(self, uid, style, custom_format=""):
        """根据用户选择的风格，获取一个UID对应的显示名称。"""
        user = self.user_info.get(uid)
        if not user: return uid
        qq, nickname, remark = user.get('qq', uid), user.get('nickname', ''), user.get('remark', '')
        default_name = remark or nickname or qq
        
        if style == 'default': return default_name
        if style == 'nickname': return nickname or qq
        if style == 'qq': return qq
        if style == 'uid': return uid
        if style == 'custom':
            return custom_format.format(
                nickname=nickname or "N/A", remark=remark or "N/A", qq=qq, uid=uid
            )
        return default_name

    def get_filename(self, uid, timestamp_str, use_markdown=False):
        """为一对一聊天记录生成标准的文件名，并附加时间戳。"""
        ext = ".md" if use_markdown else ".txt"
        user = self.user_info.get(uid)
        if not user: return f"{uid}{timestamp_str}{ext}"
        
        qq, nickname, remark = user.get('qq', uid), user.get('nickname', ''), user.get('remark', '')
        
        name_part = nickname or qq
        remark_part = f"(备注-{remark})" if remark else ""
        safe_name_part = re.sub(r'[\\/*?:"<>|]', "", name_part)
        safe_remark_part = re.sub(r'[\\/*?:"<>|]', "", remark_part)
        
        return f"{qq}_{safe_name_part}{safe_remark_part}{timestamp_str}{ext}"

# --- 时间处理函数 ---
def _parse_time_string(input_str: str) -> dict or None:
    """
    极度人性化地解析各种日期时间格式。
    返回一个包含年月日时分秒的字典，未提供则为None。
    """
    if not input_str: return None
    s = input_str.strip()
    s = re.sub(r'[/.年月]', '-', s)
    s = re.sub(r'[时分]', ':', s)
    s = re.sub(r'[日秒]', '', s)
    s = s.strip()
    match = re.match(
        r'(?:(\d{4}|\d{2})-)?(\d{1,2})-(\d{1,2})'
        r'(?:\s+(\d{1,2})' r'(?::(\d{1,2})' r'(?::(\d{1,2})' r')?)?)?', s)
    if not match: return None
    year, month, day, hour, minute, second = match.groups()
    now = datetime.now()
    if year:
        if len(year) == 2: year = f"20{year}"
    else: year = str(now.year)
    try:
        datetime(int(year), int(month), int(day))
    except ValueError: return None
    return {
        'year': int(year), 'month': int(month), 'day': int(day),
        'hour': int(hour) if hour is not None else None,
        'minute': int(minute) if minute is not None else None,
        'second': int(second) if second is not None else None
    }

def get_time_range(path_title):
    """
    【交互功能】提示用户输入时间范围，并返回处理后的起始和结束时间戳。
    """
    print(f"\n--- {path_title} ---")
    print("格式:YYYY-MM-DD HH:MM:SS (年可选, 符号可为-/.或年月日)")
    print("留空则导出全部。只输入日期则包含全天。")
    start_ts, end_ts = None, None
    while True:
        start_str = input("请输入开始时间 (例如 6-23 或 2025-06-23 08:30): ").strip()
        if not start_str: break
        parts = _parse_time_string(start_str)
        if not parts:
            print("  -> 格式无法识别，请重新输入或直接回车跳过。")
            continue
        h = parts['hour'] if parts['hour'] is not None else 0
        m = parts['minute'] if parts['minute'] is not None else 0
        s = parts['second'] if parts['second'] is not None else 0
        try:
            start_dt = datetime(parts['year'], parts['month'], parts['day'], h, m, s)
            start_ts = int(start_dt.timestamp())
            print(f"  -> 开始时间设定为: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            break
        except ValueError: print("  -> 时间值无效 (例如 小时为25)，请重新输入。")
    while True:
        end_str = input("请输入结束时间 (例如 6-23 或 2025-06-23 18:00): ").strip()
        if not end_str: break
        parts = _parse_time_string(end_str)
        if not parts:
            print("  -> 格式无法识别，请重新输入或直接回车跳过。")
            continue
        h_part, m_part, s_part = parts['hour'], parts['minute'], parts['second']
        if h_part is None: h, m, s = 23, 59, 59
        else:
            h = h_part
            m = m_part if m_part is not None else 0
            s = s_part if s_part is not None else 0
        try:
            end_dt = datetime(parts['year'], parts['month'], parts['day'], h, m, s)
            if start_ts and end_dt.timestamp() < start_ts:
                print("  -> 错误: 结束时间不能早于开始时间，请重新输入。")
                continue
            end_ts = int(end_dt.timestamp())
            print(f"  -> 结束时间设定为: {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            break
        except ValueError: print("  -> 时间值无效 (例如 小时为25)，请重新输入。")
    return start_ts, end_ts

# --- 核心消息解析函数 ---
def get_placeholder(value, placeholder="N/A"):
    """处理空值或"0"，返回占位符"""
    return value if value and str(value) != "0" else placeholder

def format_timestamp(ts, fmt="%Y-%m-%d %H:%M:%S"):
    """将时间戳格式化为易读的日期时间字符串"""
    if isinstance(ts, int) and ts > 0:
        try:
            return datetime.fromtimestamp(ts).strftime(fmt)
        except (OSError, ValueError): return f"时间戳({ts})"
    return "N/A"

def _sanitize_newlines(text: str) -> str:
    """将文本中的换行符替换为指定的占位符。"""
    if not isinstance(text, str):
        return str(text)
    return text.replace("\n", "[%\\n%]")

def _extract_readable_text(data: bytes) -> str or None:
    """
    【核心抢救逻辑】当标准Protobuf解码失败时，调用此函数尝试从原始字节流中强行提取可读的文本片段。
    """
    if not data: return None
    try:
        decoded_str = data.decode("utf-8", errors="replace")
        pattern = r"[a-zA-Z0-9\u4e00-\u9fa5\s.,!?;:\'\"()\[\]{}_\-+=*/\\|<>@#$%^&~]+"
        fragments = re.findall(pattern, decoded_str)
        return max(fragments, key=len).strip() if fragments else None
    except Exception: return None

def _parse_single_segment(segment: dict) -> str:
    """内部辅助函数，为引用消息提供原文的文本摘要，或为其他消息提供基础解析。"""
    if not isinstance(segment, dict): return ""
    msg_type = segment.get(PB_MSG_TYPE)
    
    if msg_type == 6:  # QQ表情
        desc = segment.get(PB_EMOJI_DESC, b'').decode('utf-8', 'ignore')
        # 去掉开头的'/'
        return f"[QQ表情: {desc.lstrip('/')}]" if desc else "[QQ表情]"
    if msg_type == 2:
        if segment.get(PB_MSG_SUBTYPE) == 1: return "[动画表情]"
        if segment.get(PB_IMAGE_IS_FLASH) == 1: return "[闪照]"
        return "[图片]"
    if msg_type == 4:
        duration = segment.get(PB_VOICE_DURATION)
        return f'[语音] {duration}"' if isinstance(duration, int) and duration > 0 else "[语音]"
    if msg_type == 9:
        title = segment.get("48403", {}).get(PB_REDPACKET_TITLE, b"").decode("utf-8", "ignore")
        rp_type = segment.get(PB_REDPACKET_TYPE)
        if rp_type == 6:
            return f"[口令红包] {title}"
        elif rp_type == 15:
            return f"[语音红包] {title}"
        else:
            return f"[红包] {title}"
    if msg_type == 11 and PB_MARKET_FACE_TEXT in segment:
        text = segment[PB_MARKET_FACE_TEXT].decode("utf-8", "ignore")
        return _sanitize_newlines(text)
    if PB_TEXT_CONTENT in segment:
        text = segment.get(PB_TEXT_CONTENT, b"").decode("utf-8", "ignore")
        return _sanitize_newlines(text)
    if msg_type == 5: return "[视频]"
    return f"[{MSG_TYPE_MAP.get(msg_type, '消息')}]"

def _decode_interactive_gray_tip(segment: dict, profile_mgr, name_style, name_format) -> dict or None:
    """解析互动式灰字提示（如戳一戳、拍一拍），返回结构化字典用于后续特殊格式化。"""
    try:
        xml = segment.get(PB_GRAYTIP_INTERACTIVE_XML, b"").decode("utf-8", "ignore")
        uids = re.findall(r'<qq uin="([^"]+)"', xml)
        texts = re.findall(r'<nor txt="([^"]*)"', xml)
        if len(uids) >= 2 and len(texts) >= 1:
            actor = profile_mgr.get_display_name(uids[0], name_style, name_format)
            target = profile_mgr.get_display_name(uids[1], name_style, name_format)
            verb = _sanitize_newlines(texts[0]) if texts and texts[0] else "戳了戳"
            suffix = _sanitize_newlines(texts[1]) if len(texts) > 1 else ""
            return {"type": "interactive_tip", "actor": actor, "target": target,
                    "verb": verb, "suffix": suffix}
    except Exception: return None

def decode_gray_tip(segment: dict, profile_mgr, name_style, name_format, export_config) -> dict or str or None:
    """
    根据导出配置，解析或过滤灰字提示。
    """
    interactive = _decode_interactive_gray_tip(segment, profile_mgr, name_style, name_format)
    if interactive:
        return interactive if export_config.get('show_poke') else None
    
    if PB_RECALLER_UID in segment:
        if not export_config.get('show_recall'):
            return None
        
        recaller_uid_raw = segment.get(PB_RECALLER_UID)
        recaller_uid = ""
        if isinstance(recaller_uid_raw, bytes):
            recaller_uid = recaller_uid_raw.decode('utf-8', 'ignore')
        elif isinstance(recaller_uid_raw, str):
            recaller_uid = recaller_uid_raw

        display_name = profile_mgr.get_display_name(recaller_uid, name_style, name_format)
        
        if display_name == recaller_uid:
            fallback_name_raw = segment.get(PB_RECALLER_NAME)
            if isinstance(fallback_name_raw, bytes):
                display_name = fallback_name_raw.decode('utf-8', 'ignore') or recaller_uid
            elif isinstance(fallback_name_raw, str):
                display_name = fallback_name_raw or recaller_uid

        recall_suffix = ""
        if export_config.get('show_recall_suffix'):
            recall_suffix_raw = segment.get(PB_RECALL_SUFFIX)
            temp_suffix = ""
            if isinstance(recall_suffix_raw, bytes):
                temp_suffix = recall_suffix_raw.decode('utf-8', 'ignore')
            elif isinstance(recall_suffix_raw, str):
                temp_suffix = recall_suffix_raw
            recall_suffix = _sanitize_newlines(temp_suffix)

        message = f"[{display_name} 撤回了一条消息"
        if recall_suffix:
            message += f" {recall_suffix}"
        message += "]"
        return message

    return None # 过滤掉所有其他类型的灰字提示

def decode_ark_message(segment: dict) -> str or None:
    """解析并过滤Ark卡片消息，只保留需要的类型。"""
    try:
        json_str = segment.get(PB_ARK_JSON)
        if not json_str: return None
        data = json.loads(json_str.decode("utf-8", "ignore") if isinstance(json_str, bytes) else json_str)
        app, prompt = data.get("app"), data.get("prompt", "")
        if app == "com.tencent.contact.lua" and "推荐联系人" in prompt: return f"[名片] {_sanitize_newlines(prompt)}"
        if app == "com.tencent.miniapp_01" and "[QQ小程序]" in prompt: return _sanitize_newlines(prompt)
        if app == "com.tencent.multimsg":
            source = data.get("meta", {}).get("detail", {}).get("source", "未知")
            summary = data.get("meta", {}).get("detail", {}).get("summary", "查看转发")
            return f"[聊天记录] {_sanitize_newlines(source)}: {_sanitize_newlines(summary)}"
        return None
    except Exception: return "[卡片-解析失败]"

def decode_message_content(content, timestamp, profile_mgr, name_style, name_format, export_config, is_timeline=False) -> list or None:
    """
    【核心消息解析函数】负责将原始字节流解码为可读的消息部分列表。
    :param is_timeline: 标志位，用于决定引用消息的格式。
    """
    if not content: return None
    try:
        decoded, _ = blackboxprotobuf.decode_message(content)
        segments_data = decoded.get(PB_MSG_CONTAINER)
        if segments_data is None: return ["[结构错误: 未找到消息容器]"]
        segments = segments_data if isinstance(segments_data, list) else [segments_data]
        parts = []
        for seg in segments:
            if not isinstance(seg, dict): continue
            msg_type = seg.get(PB_MSG_TYPE)
            part = None
            if msg_type not in MSG_TYPE_MAP: continue
            
            if msg_type == 1:
                text = seg.get(PB_TEXT_CONTENT, b"").decode("utf-8", "ignore")
                part = _sanitize_newlines(text)
            elif msg_type == 7: # 引用消息
                ts = seg.get(PB_REPLY_ORIGIN_TS)
                origin_content = ""
                
                # 优先从内容缓存中获取最准确的原文
                if ts in MESSAGE_CONTENT_CACHE:
                    origin_content = MESSAGE_CONTENT_CACHE[ts]
                # 如果内容缓存没有，再尝试从“抢救缓存”获取
                elif ts in SALVAGE_CACHE:
                    origin_content = _sanitize_newlines(SALVAGE_CACHE[ts])
                # 如果都没有，才回退到解析引用自带的摘要
                else:
                    raw_origin_content = seg.get(PB_REPLY_ORIGIN_SUMMARY_TEXT, b"").decode("utf-8", "ignore")
                    origin_content = _sanitize_newlines(raw_origin_content)
                    if not origin_content:
                        # 如果摘要为空，尝试解析原始消息对象
                        origin_obj_list = seg.get(PB_REPLY_ORIGIN_OBJ)
                        if origin_obj_list:
                             # 即使只有一个对象，也可能被包裹在列表中
                            origin_obj_list = origin_obj_list if isinstance(origin_obj_list, list) else [origin_obj_list]
                            origin_content_parts = [_parse_single_segment(o) for o in origin_obj_list]
                            origin_content = " ".join(filter(None, origin_content_parts))

                s_uid = seg.get(PB_REPLY_ORIGIN_SENDER_UID, b"").decode("utf-8")
                sender = profile_mgr.get_display_name(get_placeholder(s_uid), name_style, name_format)

                if is_timeline:
                    r_uid = seg.get(PB_REPLY_ORIGIN_RECEIVER_UID, b"").decode("utf-8")
                    receiver = profile_mgr.get_display_name(get_placeholder(r_uid), name_style, name_format)
                    part = f"[引用->{format_timestamp(ts)} {sender} -> {receiver}: {origin_content}]"
                else:
                    part = f"[引用->{format_timestamp(ts)} {sender}: {origin_content}]"

            elif msg_type == 21: # 通话
                status = seg.get(PB_CALL_STATUS, b"").decode("utf-8", "ignore")
                call_type = "语音通话" if seg.get(PB_CALL_TYPE) == 1 else "视频通话" if seg.get(PB_CALL_TYPE) == 2 else "通话"
                part = f"[{call_type}] {status}"
            elif msg_type == 4: # 语音
                text_raw = seg.get(PB_VOICE_TO_TEXT, b"").decode("utf-8", "ignore")
                if text_raw and export_config.get('show_voice_to_text'):
                    text = _sanitize_newlines(text_raw)
                    part = f"[语音] 转文字：{text}"
                else:
                    part = "[语音]"
            elif msg_type == 8: part = decode_gray_tip(seg, profile_mgr, name_style, name_format, export_config)
            elif msg_type == 10: part = decode_ark_message(seg)
            else: part = _parse_single_segment(seg)
            if part: parts.append(part)
        return parts or None
    except Exception:
        salvaged = None
        try:
            match = re.search(r"(\[[^\]]{1,10}\])", content.decode("utf-8", "ignore"))
            if match: salvaged = match.group(1)
        except Exception: pass
        if not salvaged: salvaged = _extract_readable_text(content)
        if salvaged:
            SALVAGE_CACHE[timestamp] = salvaged
            return [_sanitize_newlines(salvaged)]
        b64 = f"[解码失败-BASE64] {base64.b64encode(content).decode('ascii')}"
        SALVAGE_CACHE[timestamp] = b64
        return [b64]

# --- 用户交互与选择 ---
def select_export_mode(path_title):
    """让用户选择主导出模式。"""
    print(f"\n--- {path_title} ---")
    options = ["导出一个文件", "导出全部好友", "导出分组", "导出指定好友", "导出用户信息列表", "[设置]"]
    for i, opt in enumerate(options): print(f"  {i+1}. {opt}")
    while True:
        choice = input(f"请输入选项序号 (1-{len(options)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options): return int(choice)
        exit(1)

def manage_export_config(path_title, config_mgr):
    """管理导出配置的交互菜单"""
    options = {
        '1': 'show_recall', '2': 'show_recall_suffix',
        '3': 'show_poke', '4': 'show_voice_to_text',
        '5': 'export_markdown'
    }
    labels = {
        'show_recall': "撤回提示", 'show_recall_suffix': "个性化撤回提示",
        'show_poke': "戳一戳提示", 'show_voice_to_text': "语音转换文本",
        'export_markdown': "输出为 Markdown (.md)"
    }

    temp_config = config_mgr.config.copy()
    
    while True:
        print(f"\n--- {path_title} ---")
        print("> 内容格式")
        for key in ['1', '2', '3', '4']:
            config_key = options[key]
            status = "开" if temp_config.get(config_key) else "关"
            print(f"  {key}. [{status}] {labels[config_key]}")
        print("> 其他设置")
        status_md = "开" if temp_config.get('export_markdown') else "关"
        print(f"  5. [{status_md}] {labels['export_markdown']}")

        choice_str = input("请输入要切换的选项序号 (可多选，如 1 2 或 13)，回车键保存并返回: ").strip()

        if not choice_str:
            config_mgr.config = temp_config
            config_mgr.save_config()
            break
        
        selected_keys = re.findall(r'\d', choice_str)
        toggled = False
        for key in selected_keys:
            if key in options:
                config_key = options[key]
                temp_config[config_key] = not temp_config[config_key]
                toggled = True
        
        if not toggled:
            break


def select_user_list_mode(path_title):
    """让用户选择导出用户列表的范围。"""
    print(f"\n--- {path_title} ---")
    options = ["仅好友", "全部缓存用户"]
    for i, opt in enumerate(options): print(f"  {i+1}. {opt}")
    while True:
        choice = input(f"请输入选项序号 (1-{len(options)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options): return int(choice)
        return None # 无效输入则返回

def select_name_style(path_title):
    """让用户选择导出的名称显示格式，并支持回车使用默认值。"""
    print(f"\n--- {path_title} ---")
    styles = {'1': 'default', '2': 'nickname', '3': 'qq', '4': 'uid', '5': 'custom'}
    descs = {'1': "备注/昵称 (优先显示备注) [默认]", '2': "昵称", '3': "QQ号码", '4': "UID", '5': "自定义格式"}
    for k, v in descs.items(): print(f"  {k}. {v}")
    
    while True:
        choice = input(f"请输入选项序号 (1-5, 直接回车使用默认值): ").strip()
        
        if not choice:
            choice = '1'
            
        if choice in styles:
            style = styles[choice]
            custom_fmt = ""
            if style == 'custom':
                print("可用占位符: {nickname}, {remark}, {qq}, {uid}")
                custom_fmt = input("请输入自定义格式: ").strip()
            return style, custom_fmt
        print("  -> 无效输入，请重试。")

def select_friends(profile_mgr, path_title):
    """
    【交互功能】提供一个可交互的菜单让用户选择一个或多个好友。
    支持按分组查看或全部展开，全部展开时会保留分组标题。
    """
    friends_by_group = {}
    for uid, info in profile_mgr.user_info.items():
        if uid == profile_mgr.my_uid: continue
        gid = info['group_id']
        if gid not in friends_by_group: friends_by_group[gid] = []
        friends_by_group[gid].append(uid)
    
    while True:
        print(f"\n--- {path_title} ---")
        sorted_groups = sorted(friends_by_group.items(), key=lambda i: profile_mgr.group_info.get(i[0], str(i[0])))
        choices = {str(i+1): gid for i, (gid, uids) in enumerate(sorted_groups)}
        for i, (gid, uids) in enumerate(sorted_groups):
            name = profile_mgr.group_info.get(gid, f"分组_{gid}")
            print(f"  {i+1}. {name} ({len(uids)}人)")
        print("  a. 全部展开")
        choice = input("请选择分组序号或'a'全部展开: ").strip().lower()
        
        gids_to_show = []
        group_name_for_title = ""
        if choice == 'a':
            gids_to_show = [gid for gid, uids in sorted_groups]
            group_name_for_title = "全部展开"
        elif choice in choices:
            selected_gid = choices[choice]
            gids_to_show.append(selected_gid)
            group_name_for_title = profile_mgr.group_info.get(selected_gid, f"分组_{selected_gid}")
        else:
            return None # 无效输入则返回

        print(f"\n--- {path_title} > {group_name_for_title} ---")
        selectable = {}
        i = 1
        for gid in gids_to_show:
            if choice == 'a': # 如果是全部展开模式，额外显示分组标题
                current_group_name = profile_mgr.group_info.get(gid, f"分组_{gid}")
                print(f"\n--- {current_group_name} ---")
            
            if not friends_by_group.get(gid):
                print("  (此分组下没有好友)")
                continue
            
            for uid in friends_by_group[gid]:
                info = profile_mgr.user_info[uid]
                remark = f" (备注: {info['remark']})" if info['remark'] else ""
                display = f"{info['nickname'] or info['qq']}{remark} (QQ: {info['qq']})"
                print(f"  {i}. {display}")
                selectable[str(i)] = uid
                i += 1
        
        if not selectable:
            print("没有可供选择的好友。")
            continue
            
        choices_str = input("请输入好友序号 (可多选，用空格或逗号分隔): ").strip()
        selected = [selectable[c] for c in re.split(r'[\s,]+', choices_str) if c in selectable]
        if selected: return list(set(selected))
        # 无效或空输入，循环回到分组选择
        continue


def select_group(profile_mgr, path_title):
    """让用户从分组列表中选择一个分组。"""
    print(f"\n--- {path_title} ---")
    friends_by_group = {info.get('group_id'): [] for uid, info in profile_mgr.user_info.items() if uid != profile_mgr.my_uid}
    for uid, info in profile_mgr.user_info.items():
        if uid != profile_mgr.my_uid: friends_by_group[info.get('group_id')].append(uid)
    
    sorted_groups = sorted(profile_mgr.group_info.items(), key=lambda i: i[1])
    choices = {str(i+1): gid for i, (gid, name) in enumerate(sorted_groups)}
    
    print("  a. 全部导出")
    for i, (gid, name) in enumerate(sorted_groups):
        count = len(friends_by_group.get(gid, []))
        print(f"  {i+1}. {name} ({count}人)")

    while True:
        choice = input(f"请输入分组序号: ").strip().lower()
        if choice == 'a':
            return 'all_groups'
        if choice in choices: 
            return choices[choice]
        return None # 无效输入则返回

# --- 导出执行逻辑 ---
def process_and_write(output_path, rows, profile_mgr, config):
    """将查询到的数据库行处理并写入文件，支持txt和markdown两种格式。"""
    is_markdown = config['export_config'].get('export_markdown', False)
    
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        if is_markdown:
            # 【还原】移除之前复杂的换行逻辑，回归简单实现
            last_date = None
            last_sender_key = None
            for row in rows:
                ts, s_uid, p_uid, content = row
                parts = decode_message_content(content, ts, profile_mgr, config['name_style'], config['name_format'], config['export_config'], config['is_timeline'])
                if not parts: continue
                
                dt_object = datetime.fromtimestamp(ts)
                current_date = dt_object.strftime("%Y-%m-%d")
                current_time = dt_object.strftime("%H:%M:%S")

                sender_display = profile_mgr.get_display_name(get_placeholder(s_uid), config['name_style'], config['name_format'])
                if sender_display == "N/A":
                    sender_key = "[系统提示]"
                elif config['is_timeline']:
                    if get_placeholder(s_uid) == get_placeholder(p_uid): p_uid = profile_mgr.my_uid
                    receiver_display = profile_mgr.get_display_name(get_placeholder(p_uid), config['name_style'], config['name_format'])
                    sender_key = f"{sender_display} -> {receiver_display}"
                else:
                    sender_key = sender_display

                if current_date != last_date:
                    f.write(f"\n# {current_date}\n")
                    last_date = current_date
                    last_sender_key = None
                
                if sender_key != last_sender_key:
                    f.write(f"\n### {sender_key}\n")
                    last_sender_key = sender_key

                main_text_parts = []
                quote_content = ""

                is_reply = isinstance(parts[0], str) and parts[0].startswith('[引用->')
                
                if not is_reply and isinstance(parts[0], dict) and parts[0].get("type") == "interactive_tip":
                    tip = parts[0]
                    main_text_parts.append(f"{tip['actor']} {tip['verb']} {tip['target']}{tip['suffix']}")
                else:
                    for p in parts:
                        p_str = str(p)
                        match = re.search(r'\[引用->(.*)\]', p_str)
                        if match:
                            quote_content = match.group(1)
                        else:
                            main_text_parts.append(p_str)
                
                main_text = " ".join(main_text_parts)
                
                if not is_reply:
                    MESSAGE_CONTENT_CACHE[ts] = main_text

                if sender_key == "[系统提示]" and main_text.startswith('[') and main_text.endswith(']'):
                     main_text = main_text[1:-1]
    
                f.write(f"* {current_time} {main_text}\n")
                if quote_content:
                    f.write(f"  > {quote_content}\n\n")
                
                count += 1

        else: # 【修改】非Markdown模式的逻辑
            for row in rows:
                ts, s_uid, p_uid, content = row
                parts = decode_message_content(content, ts, profile_mgr, config['name_style'], config['name_format'], config['export_config'], config['is_timeline'])
                if not parts: continue
                
                is_reply = isinstance(parts[0], str) and parts[0].startswith('[引用->')
                text = " ".join(str(p) for p in parts if not isinstance(p, dict))
                
                if not is_reply:
                    MESSAGE_CONTENT_CACHE[ts] = text
                else:
                    # 【修改】仅在非Markdown模式下，对引用消息进行格式化
                    # 匹配格式: [引用->YYYY-MM-DD HH:MM:SS 剩余所有内容]
                    pattern = r'\[引用->(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)\]'
                    # 替换格式: [引用-> [YYYY-MM-DD HH:MM:SS] 剩余所有内容 <-]
                    replacement = r'[引用-> [\1] \2 <-]'
                    text = re.sub(pattern, replacement, text, count=1)

                time = format_timestamp(ts)
                first = parts[0]
                if isinstance(first, dict) and first.get("type") == "interactive_tip":
                    body = f"{first['actor']} {first['verb']} {first['target']}{first['suffix']}"
                    line = f"[{time}] [系统提示]: {body}\n"
                else:
                    sender = profile_mgr.get_display_name(get_placeholder(s_uid), config['name_style'], config['name_format'])
                    if sender == "N/A": sender = "[系统提示]"
                    if config['is_timeline']:
                        if get_placeholder(s_uid) == get_placeholder(p_uid): p_uid = profile_mgr.my_uid
                        receiver = profile_mgr.get_display_name(get_placeholder(p_uid), config['name_style'], config['name_format'])
                        line = f"[{time}] {sender} -> {receiver}: {text}\n"
                    else: line = f"[{time}] {sender}: {text}\n"
                f.write(line)
                count += 1
    return count

def export_timeline(db_con, config):
    """执行全局时间线导出。"""
    print("\n正在执行“全局时间线”导出...")
    start_ts, end_ts, name_style, name_format, profile_mgr, run_timestamp, export_config = config.values()
    query = f"SELECT `{COL_TIMESTAMP}`, `{COL_SENDER_UID}`, `{COL_PEER_UID}`, `{COL_MSG_CONTENT}` FROM {TABLE_NAME}"
    clauses, params = [], []
    if start_ts:
        clauses.append(f"`{COL_TIMESTAMP}` >= ?")
        params.append(start_ts)
    if end_ts:
        clauses.append(f"`{COL_TIMESTAMP}` <= ?")
        params.append(end_ts)
    if clauses: query += f" WHERE {' AND '.join(clauses)}"
    query += f" ORDER BY `{COL_TIMESTAMP}` ASC"
    
    cur = db_con.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    if not rows:
        print("查询完成，但未能获取任何记录。")
        return
        
    ext = ".md" if export_config.get('export_markdown') else ".txt"
    filename = f"{_TIMELINE_FILENAME_BASE}{run_timestamp}{ext}"
    path = os.path.join(OUTPUT_DIR, filename)
    
    process_config = config.copy()
    process_config['is_timeline'] = True
    count = process_and_write(path, rows, profile_mgr, process_config)
    print(f"\n处理完成！共导出 {count} 条有效消息到 {path}")

def export_one_on_one(db_con, friend_uid, config, out_dir=None, index=None, total=None):
    """导出一个好友的一对一聊天记录。"""
    start_ts, end_ts, name_style, name_format, profile_mgr, run_timestamp, export_config = config.values()
    
    friend_info = profile_mgr.user_info.get(friend_uid, {})
    friend_nickname = friend_info.get('nickname', friend_uid)
    friend_remark = friend_info.get('remark', '')
    friend_display_name = f"{friend_nickname or friend_uid}{f'(备注-{friend_remark})' if friend_remark else ''}"
    
    if index and total:
        print(f"正在导出 ({index}/{total}) {friend_display_name}... ", end="")
    else:
        print(f"\n正在导出与 {friend_display_name} 的聊天记录...")
    
    query = f"SELECT `{COL_TIMESTAMP}`, `{COL_SENDER_UID}`, `{COL_PEER_UID}`, `{COL_MSG_CONTENT}` FROM {TABLE_NAME}"
    clauses = [f"`{COL_PEER_UID}` = ?"]
    params = [friend_uid]

    if start_ts:
        clauses.append(f"`{COL_TIMESTAMP}` >= ?")
        params.append(start_ts)
    if end_ts:
        clauses.append(f"`{COL_TIMESTAMP}` <= ?")
        params.append(end_ts)
    query += f" WHERE {' AND '.join(clauses)} ORDER BY `{COL_TIMESTAMP}` ASC"
    
    cur = db_con.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    if not rows:
        print(f"-> 与 {friend_display_name} 在指定时间内无聊天记录。")
        return

    output_dir = out_dir or OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    filename = profile_mgr.get_filename(friend_uid, run_timestamp, export_config.get('export_markdown'))
    path = os.path.join(output_dir, filename)
    
    process_config = config.copy()
    process_config['is_timeline'] = False
    count = process_and_write(path, rows, profile_mgr, process_config)
    print(f"-> 共导出 {count} 条消息到 {path}")

def export_user_list(profile_mgr, list_mode, timestamp_str):
    """
    【新增功能】导出用户信息列表到txt文件。
    :param list_mode: 1 for 仅好友, 2 for 全部缓存用户
    """
    if list_mode == 1:
        print("\n正在导出好友列表...")
        users_to_export = profile_mgr.user_info
        base_filename = _FRIENDS_LIST_FILENAME
    else: # list_mode == 2
        print("\n正在导出全部缓存用户列表...")
        users_to_export = profile_mgr.all_profiles_cache
        base_filename = _ALL_USERS_LIST_FILENAME

    name, ext = os.path.splitext(base_filename)
    filename = f"{name}{timestamp_str}{ext}"
    output_path = os.path.join(OUTPUT_DIR, filename)
    
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for uid, info in users_to_export.items():
            if uid == profile_mgr.my_uid: continue # 不导出自己
            
            f.write("----------------------------------------\n")
            f.write(f"昵称: {info.get('nickname', 'N/A')}\n")
            f.write(f"备注: {info.get('remark', 'N/A')}\n")
            f.write(f"QQ: {info.get('qq', 'N/A')}\n")
            f.write(f"UID: {uid}\n")
            f.write(f"QID: {info.get('qid', 'N/A')}\n")
            f.write(f"签名: {info.get('signature', 'N/A')}\n")
            count += 1
    
    print(f"\n处理完成！共导出 {count} 位用户的信息到 {output_path}")

def main():
    """主执行函数，负责整个程序的流程控制。"""
    # 0. 解析命令行参数
    parser = argparse.ArgumentParser(description="QQ NT 聊天记录导出工具")
    parser.add_argument('--workdir', type=str, default='.', help='指定工作目录，应包含解密后的数据库文件，并将在此创建输出文件夹。')
    args = parser.parse_args()

    # 设置全局路径变量
    global DB_PATH, PROFILE_DB_PATH, OUTPUT_DIR, CONFIG_PATH
    workdir = args.workdir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(workdir, _DB_FILENAME)
    PROFILE_DB_PATH = os.path.join(workdir, _PROFILE_DB_FILENAME)
    OUTPUT_DIR = os.path.join(workdir, _OUTPUT_DIR_NAME)
    CONFIG_PATH = os.path.join(script_dir, _CONFIG_FILENAME)

    print("===== QQ聊天记录导出工具 =====")
    print(f"当前工作目录: {os.path.abspath(workdir)}")
    
    # 1. 初始化，加载所有用户信息和配置
    profile_mgr = ProfileManager(PROFILE_DB_PATH)
    profile_mgr.load_data()
    config_mgr = ConfigManager(CONFIG_PATH)
    
    # 主循环，允许从子菜单返回
    while True:
        # 2. 让用户选择主模式
        path_title = "主菜单"
        mode = select_export_mode(path_title)
        
        # 3. 统一创建主输出目录和生成本次运行的时间戳
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        run_timestamp = f"_{int(datetime.now().timestamp())}"
        
        mode_titles = {1: "导出一个文件", 2: "导出全部好友", 3: "导出分组", 4: "导出指定好友", 5: "导出用户信息列表", 6: "[设置]"}
        path_title += f" > {mode_titles.get(mode)}"
        
        # 4. 根据模式执行不同操作
        if mode == 6: # 导出配置
            manage_export_config(path_title, config_mgr)
            continue
            
        if mode == 5: # 导出用户信息列表
            list_mode = select_user_list_mode(path_title)
            if list_mode is None: continue
            export_user_list(profile_mgr, list_mode, run_timestamp)
            break 
        
        # --- 导出聊天记录流程 ---
        targets = []
        output_dir = None
        
        if mode == 1: # 全局时间线
            pass 
        elif mode == 2: # 导出全部好友
            output_dir = os.path.join(OUTPUT_DIR, "friends")
            targets = [uid for uid in profile_mgr.user_info.keys() if uid != profile_mgr.my_uid]
        elif mode == 3: # 按分组
            gid_or_all = select_group(profile_mgr, path_title)
            if gid_or_all is None: continue
            
            if gid_or_all == 'all_groups':
                all_friends_in_groups = []
                for gid in profile_mgr.group_info.keys():
                    group_name = profile_mgr.group_info.get(gid, f"分组{gid}")
                    safe_group_name = re.sub(r'[\\/*?:"<>|]', "", f"{gid}_{group_name}")
                    group_output_dir = os.path.join(OUTPUT_DIR, "friends", safe_group_name)
                    friends_in_group = [uid for uid, info in profile_mgr.user_info.items() if info.get('group_id') == gid]
                    all_friends_in_groups.append({'dir': group_output_dir, 'friends': friends_in_group})
                targets = all_friends_in_groups
            else:
                gid = gid_or_all
                name = profile_mgr.group_info.get(gid, f"分组{gid}")
                safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{gid}_{name}")
                output_dir = os.path.join(OUTPUT_DIR, "friends", safe_name)
                targets = [uid for uid, info in profile_mgr.user_info.items() if info.get('group_id') == gid]
                if not targets: print("该分组下没有好友。")
        elif mode == 4: # 指定好友
            targets = select_friends(profile_mgr, path_title)
            if targets is None: continue

        if mode != 1 and not targets:
            continue

        start_ts, end_ts = get_time_range(f"{path_title} > 设定时间范围")
        name_style, name_format = select_name_style(f"{path_title} > 设定用户标识")
        config = {
            "start_ts": start_ts, 
            "end_ts": end_ts, 
            "name_style": name_style, 
            "name_format": name_format, 
            "profile_mgr": profile_mgr,
            "run_timestamp": run_timestamp,
            "export_config": config_mgr.config
        }

        if not os.path.exists(DB_PATH):
            print(f"错误: 消息数据库文件 '{DB_PATH}' 不存在。")
            return

        try:
            with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
                if mode == 1:
                    export_timeline(con, config)
                elif mode == 3 and isinstance(targets, list) and targets and isinstance(targets[0], dict):
                    print("\n即将导出所有分组...")
                    total_friends_count = sum(len(g['friends']) for g in targets)
                    current_friend_index = 0
                    for group_data in targets:
                        group_dir = group_data['dir']
                        for friend_uid in group_data['friends']:
                            current_friend_index += 1
                            export_one_on_one(con, friend_uid, config, group_dir, current_friend_index, total_friends_count)
                else:
                    total = len(targets)
                    for i, uid in enumerate(targets):
                        export_one_on_one(con, uid, config, output_dir, i + 1, total)
        except sqlite3.Error as e:
            print(f"\n数据库错误: {e}")
        except Exception as e:
            print(f"\n发生未知错误: {e}")
            import traceback
            traceback.print_exc()
            
        break # 任务完成，退出主循环

    print("\n--- 所有任务已完成 ---")

if __name__ == "__main__":
    main()