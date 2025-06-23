# [持续更新] QQRootFastDecrypt

针对于已 root 安卓设备的快捷导出 QQ 聊天记录的脚本

文档中的环境 [termux](https://github.com/termux/termux-app/releases) (com.termux) 版本 0.119.0-beta.2(1021)

已解密的数据库统一命名为 `xxx.decrypt.db`

## 目录

> - 主要工具
>   - [# qqnt_decrypt.sh](#qqnt_decryptsh) 自动扫描 qq 账号，计算 key 并自动解密。
>   - [# export_chats.py](#export_chatspy) 从数据库中导出可读文本，提供各种导出模式。
> - 其他工具
>   - [# get_qqnt_key.sh](#get_qqnt_keysh) 自动扫描 QQ 账号并计算 key。
>   - [# sqlite_to_json.py](#sqlite_to_jsonpy) SQLite 到 JSON 导出工具。
> - 未完成的
>   - [new_export_chats.py](#new_export_chatspy) 基于 export_chats.py，重构全部逻辑

## 安装依赖

```bash
pkg update && pkg upgrade
pkg install sqlcipher python git
pip install blackboxprotobuf
```

## 下载仓库

```bash
git clone https://github.com/miniyu157/QQRootFastDecrypt.git
```

## 未完成的

### new_export_chats.py

基于 `export_chats.py` 重构，用于从数据库中导出可读文本，差异：

- 目前只有一个导出模式（即按全局时间线导出），未来添加各种导出模式，例如

  - 全量导出模式 以及 文本导出模式
  - 导出格式： txt 以及 markdown
  - 限制时间范围
  - 自定义用户标识（使用 `profile_info.decrypt.db`），例如 昵称、昵称/备注、QQ 号码、UID 或自定义占位符
  - 私聊
    - 导出某个分组中的全部好友
    - 导出全部好友
    - 导出单个好友（列出好友列表）
  - 群聊
    - 列出群聊列表，导出某个群聊的全部聊天记录

- 目前仅使用了 `nt_msg.decrypt.db` 数据库，所以用户标识全是 UID
- 在脚本所在目录的 `myqq` 文件中读取主人 UID，不存在会提示手动输入(-save 自动保存)
  > 未来使用 `profile_info.decrypt.db` 后可以输入 QQ 号码解析，与 `qqnt_decrypt.sh` 互相配合
- 目前提供了基本全部消息类型的支持：
  - 文本、文件、图片、视频、语音、QQ 卡片、红包等
  - 引用消息包含：原发送人、接收人、时间戳、消息内容
  - 系统灰色字包含戳一戳、撤回消息等系统提示，忽略好友火花提示以及无内容的系统提示等
    > ```python
    > # 定义需要被忽略的系统提示的正则表达式列表
    > IGNORE_GRAY_TIP_PATTERNS_RAW = [
    >     r"^你已对此会话开启消息免打扰$",
    >     r"^自定义撤回消息",
    >     r"由于.*未互发消息",
    >     r"你们超过.*未互发消息",
    >     r"你们的.*即将彻底消失",
    > ]
    > ```
  - 图片区分：
    **图片** **闪照** **动画表情** **商城表情(显示为 "[表情描述]"")** **QQ 表情**
  - 红包区分： **普通红包** 与 **口令红包**

## 主要工具

### qqnt_decrypt.sh

自动扫描 qq 账号，计算 key 并自动解密。默认解密 `nt_msg.decrypt.db` 和 `profile_info.decrypt.db` 两个数据库，可在源代码底部修改。

**快捷启动命令** (粘贴到 termux)

```bash
cp /storage/emulated/0/QQRootFastDecrypt/qqnt_decrypt.sh ~/qqnt_decrypt.sh && chmod +x ~/qqnt_decrypt.sh && ~/qqnt_decrypt.sh
```

**效果演示**

```
请输入解密文件的输出目录 [默认为: /storage/emulated/0/QQRootFastDecrypt]:

[信息] 正在检测QQ数据路径...
[成功] 检测到QQ数据路径: /data/user/0/com.tencent.mobileqq
----------------------------------------
[信息] 发现以下QQ账号，请选择要计算的账号：
  [1] 123456789
  [2] 987654321
----------------------------------------
请输入选项编号: 2

[信息] 正在获取密钥...
[成功] key: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
----------------------------------------
[信息] 正在处理: nt_msg.db
[成功] 解密完成: /storage/emulated/0/QQRootFastDecrypt/nt_msg.decrypt.db
----------------------------------------
[信息] 正在处理: profile_info.db
[成功] 解密完成: /storage/emulated/0/QQRootFastDecrypt/profile_info.decrypt.db
========================================
[成功] 所有任务已完成！
[信息] 解密后的文件位于目录: /storage/emulated/0/QQRootFastDecrypt
========================================
```

### export_chats.py

从数据库中导出可读文本。如果存在 `profile_info.decrypt.db`，则可以自定义用户标识；不存在的话用户标识显示为 UID。

**效果演示**

```
检测到好友信息库 'profile_info.decrypt.db'，启用好友功能。
成功加载 XX 位好友的信息。

========================================
==      QQ 聊天记录导出工具      ==
========================================

请选择导出模式:
  1. 全部导出 (按全局时间线排序)
  2. 全部导出 (按好友分类保存)
  3. 导出指定好友
请输入模式编号 (1/2/3): 3

好友列表:
  1: 用户A (昵称: 昵称A) (QQ: 111111111)
  2: 用户B (昵称: 昵称B) (QQ: 222222222)
  3: 用户C (昵称: 昵称C) (QQ: 333333333)
  4: 用户D (QQ: 444444444)
  5: 用户E (QQ: 555555555)
  6: 用户F (QQ: 666666666)
  7: 用户G (QQ: 777777777)
请输入您想导出的好友的序号: 6

是否筛选时间范围? (不需要请直接按回车)
请输入开始日期 (格式YYYY-MM-DD):
请输入结束日期 (格式YYYY-MM-DD):

请选择用户标识显示格式:
  1. 昵称 (默认)
  2. 昵称/备注 (优先显示备注)
  3. QQ号码
  4. UID
  5. 自定义格式
请输入格式编号 (1-5，默认1): 2

为正确解析对话和分类，请输入您自己的【UID】或【QQ号】: 123456789
-> 已识别用户 UID: u_RANDOMUSERIDSTRING

聊天记录库 'nt_msg.decrypt.db' 打开成功。
正在查询和加载聊天记录...
查询完成，找到 XXXX 条相关记录。
正在解析消息内容...
解析完成，共 XXX 条有效消息。
开始写入文件 "output_chats/聊天记录-666666666-用户F.txt"...
导出完成。

导出任务已完成。
```

## 其他工具

### get_qqnt_key.sh

自动扫描 QQ 账号并计算 key。

**快捷启动命令** (粘贴到 termux)

```bash
cp /storage/emulated/0/QQRootFastDecrypt/get_qqnt_key.sh ~/get_qqnt_key.sh && chmod +x ~/get_qqnt_key.sh && ~/get_qqnt_key.sh
```

**效果演示**

```
----------------------------------------
[信息] 发现以下QQ账号，请选择要计算的账号：
  [1] 123456789
  [2] 987654321
----------------------------------------
请输入选项编号: 2

[信息] 正在处理...
========================================
          计算完成 - 结果如下
========================================
QQ: 987654321
UID: u_RANDOMUSERIDSTRING
QQ_UID_hash: randomhashvalueabcdef123456
QQ_path_hash: anotherrandomhash789012
rand: R4nDoM
key: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
========================================
```

### sqlite_to_json.py

SQLite 到 JSON 导出工具，可以指定忽略某些列或只启用某些列。

**使用帮助**

```
positional arguments:
  db_path               源 SQLite 数据库文件的路径
  table_name            数据库中要导出的表名

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        输出的 JSON 文件路径 (可选, 默认将根据输入自动生成)
  -e ENABLE [ENABLE ...], --enable ENABLE [ENABLE ...]
                        [白名单模式] 只导出指定的列，可提供多个列名，用空格分隔。
  -i IGNORE [IGNORE ...], --ignore IGNORE [IGNORE ...]
                        [黑名单模式] 导出时忽略指定的列，可提供多个列名，用空格分隔。
```

**示例：** 导出用户信息归档中全部的用户昵称以及 uid

_代码_

```bash
python sqlite_to_json.py profile_info.decrypt.db profile_info_v6 -e "1000" "20002"
```

_输出_

```
成功以只读模式连接到数据库: profile_info.decrypt.db
从表 'profile_info_v6' 中查询到 XXXXX 行数据。
白名单模式已启用。将只导出列: ['1000', '20002']
数据已成功导出到: profile_info.decrypt.profile_info_v6.json
数据库连接已关闭。
```

> QQNT 的数据库、表名、列名含义，以及 protobuf 定义参考：https://github.com/AnotherUser/AnotherRepo/
