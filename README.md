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

<details>
<summary>展开/隐藏详情</summary>

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

</details>

## 主要工具

### qqnt_decrypt.sh

自动扫描 qq 账号，计算 key 并自动解密数据库。默认解密 `nt_msg.decrypt.db` 和 `profile_info.decrypt.db`，可使用代码编辑器从底部修改。

**快捷启动**

```bash
bash /storage/emulated/0/QQRootFastDecrypt/qqnt_decrypt.sh
```

### export_chats.py

从数据库中导出可读文本。额外需要 `profile_info.decrypt.db` 加载用户信息列表以及主人身份信息。

脚本通过交互式菜单运行，提供了丰富的导出选项和配置。

#### 导出模式

* **导出合并的时间线单文件**: 将多个会话的聊天记录按时间顺序合并到一个文件中。
    * 支持选择范围：**全部好友**、**指定分组** 或 **手动选择的好友**。
* **导出每个好友单独的文件**: 为每个好友生成一个独立的聊天记录文件。
    * 支持的导出方式：**全部好友**、**按分组**（可为每个分组创建子文件夹）、**指定好友**。

#### 设置与配置

所有配置项均可通过菜单修改，并自动保存至 `export_config.json` 文件。

* **输出格式**: 可在 `TXT`、`MD` 和 `HTML` 之间自由切换。
* **HTML模板**: 当输出格式为HTML时，可从 `html_templates` 文件夹中选择不同的外观模板。
* **用户标识格式**: 可持久化设定好友名称的显示格式（如备注、昵称、QQ号或自定义模板）。
* **文件头信息**: 可选择是否在每个导出文件的开头添加一份包含导出范围、时间、数据库校验和等信息的摘要。
* **内容显示开关**:
    * 是否显示撤回提示（支持个性化后缀）。
    * 是否显示“拍一拍”、“戳一戳”等互动提示。
    * 是否显示语音消息的转录文本。
    * 是否显示图片/视频的尺寸和时长等详细信息（默认关闭）。

#### HTML 模板

仓库中存放了基础模板 `default.html` 以及少量的预设模板，提供丰富的 css 类以及元素嵌套，皆可在最大程度上进行模板创作。

欢迎提交 pull request！

#### 消息解析详情

* **红包**: 精确区分为 `[普通红包]`、`[口令红包]` 和 `[语音红包]`，并显示其描述文本。
* **图片与表情**:
    * **图片/闪照**: 显示为 `[图片]` 或 `[闪照]`，开启媒体信息后可显示为 `[图片 1920x1080]`。
    * **表情**: 覆盖多种类型，如 `[QQ表情: 捂脸]`、`[动画表情]`、`[商城表情]`(显示为表情描述)、`[超级QQ秀: 七夕快乐]` 以及 `[互动表情: 比心]`、`[平底锅]x99` 等。
* **多媒体**: `[视频]` 可显示尺寸和时长，`[文件]` 可显示完整文件名。
* **卡片与分享**: 支持位置卡片（显示地点与地址）、音乐分享（显示歌名与作者）、文件、小程序、名片和合并转发的聊天记录。
* **系统与互动**: 能正确显示撤回、拍一拍/戳一戳、位置共享状态等。
* **引用消息**: 能够正确显示包括互动表情在内的各类复杂消息的原文摘要。

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

> QQNT 的数据库、表名、列名含义，以及 protobuf 定义参考：https://github.com/QQBackup/QQDecrypt/tree/main/docs/view/db_file_analysis
