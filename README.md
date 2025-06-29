# QQRootFastDecrypt

针对于已 root 安卓设备的快捷导出 QQ 聊天记录的脚本

文档中使用的环境 [termux](https://github.com/termux/termux-app/releases) (com.termux) 版本 0.119.0-beta.3(1022)

已解密的数据库统一命名为 `xxx.decrypt.db`

[更新日志](https://github.com/miniyu157/QQRootFastDecrypt/blob/main/CHANGELOG.md)

## 快速开始

```bash
bash <(curl -sL 'https://gitee.com/KlxPiao/qqroot-fast-decrypt-start/raw/master/start.sh')
```

## 慢速开始

> 在 **慢速开始** 中，推荐安装到 `/storage/emulated/0/QQRootFastDecrypt`

### 1. 安装依赖

```bash
pkg update && pkg upgrade
pkg install sqlcipher python git
pip install blackboxprotobuf
```

### 2. 下载仓库

```bash
git clone https://github.com/miniyu157/QQRootFastDecrypt.git
```

### 3. 进入目录

```
cd /storage/emulated/0/QQRootFastDecrypt
```

### 4. 启动解密脚本

```bash
bash qqnt_decrypt.sh
```

### 5. 导出聊天记录
    
```
python export_chats.py
```

## 主要工具

### qqnt_decrypt.sh

自动扫描 qq 账号，计算 key 并自动解密数据库。默认解密 `nt_msg.decrypt.db` 和 `profile_info.decrypt.db`，可使用代码编辑器从底部修改。

**快捷启动**

```bash
bash /storage/emulated/0/QQRootFastDecrypt/qqnt_decrypt.sh
```

### export_chats.py

从数据库中导出可读文本。需要 `profile_info.decrypt.db` 加载用户信息列表以及主人身份信息。

导出模式

- 单个文件 全部好友按时间线排序在一个文件中
- 全部好友 存放在一个文件夹中，每个好友一个文件
- 按分组 导出某个分组或全部分组 每个好友一个文件
- 指定好友 列出好友列表，可以进入分组或全部展开

设置

- 美化输出为 Markdown(.md) 或 .txt
- 开关消息类型，关闭后不导出指定类型的消息
  
涵盖基本全部消息类型

- 红包区分 普通/口令/语音
- 图片区分 闪照/图片/动画表情/QQ表情(显示描述)/商城表情(显示描述)
- 引用消息 包含原时间戳 发送人 接收人(如果有的话) 原消息内容
- 系统灰字 戳一戳提示/撤回提示
- 过滤好友火花提示以及广告卡片

待优化：少部分引用消息的乱码，markdown 引用消息的换行

```text
### 用户B
* 23:12:37 [动画表情]

# 0000-00-01

### 用户B
* 00:21:46 [动画表情]
* 00:21:51 被引用的消息

### 用户A
* 00:22:03 [动画表情]
* 00:22:08 消息内容内容内容

### 用户B
* 00:22:10 主消息内容
  > [0000-00-20 00:21:51] 用户B: 被引用的消息

* 00:22:10 消息内容
```

## 其他工具

### get_qqnt_key.sh

自动扫描 QQ 账号并计算 key。

**快捷启动**

```bash
bash /storage/emulated/0/QQRootFastDecrypt/get_qqnt_key.sh
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
