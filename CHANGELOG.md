# CHANGELOG

### 提交 21bc68d

    删除 export_chats.py，重命名 new_export_chats.py -> export_chats.py

### 提交 b1a8425

    更新 new_export_chats.py

- 交互
  - 模式 **指定好友导出** 的好友列表全部展开时，按照分组排序
  - 选项 **用户标识显示格式** 提供默认值
- 逻辑
  - 生成的文件添加时间戳
  - 模式 **全局时间线**  下，修复 output_chats 文件夹不创建的问题
  - 撤回消息 中用户标识 由 **昵称** 改为脚本选择的标识
  - 撤回消息 解析用户自定义后缀
  - 移除全部火花提示以及其他系统提示
    
### 提交 457e904

    更新 new_export_chats.py

- 差异
  - 连接 `profile_info.decrypt.db` 读取 UID 以及用户信息
  - 模式
    - 全局时间线
    - 导出全部好友
    - 按分组导出
    - 指定好友导出
    - 导出用户信息列表
      - 仅好友
      - 全部缓存用户
  - 新增选项 设定时间范围
  - 新增选项 用户标识显示格式

### 提交 471c1a9

    更新 new_export_chats.py

- 差异
  - 修复引用 **protobuf 解码失败的消息** 时错误解码
  - 语音消息显示转文字内容

### 提交 ae0f79e

    更新 new_export_chats.py

- 差异
  - 戳一戳互动，也使用 UID
  - 移除无内容系统提示
  - 红包区分为 **普通红包** 与 **口令红包**，并显示描述
  - 图片区分为 **图片** 与 **闪照**
  - 对于 **protobuf 解码失败的消息**，读取可读文本

### 提交 55e630d

    新增 new_export_chats.py，为 export_chats.py 的重构版本

- 相较于 `export_chats.py` 差异
  - 优化核心逻辑
  - 基本涵盖全部消息类型，包括戳一戳等互动提示
  - 功能回退：只有全局时间线的导出模式，以 UID 作为用户标识
  
### 提交 a353c43

    新增四个工具脚本

- 新增文件
  - qqnt_decrypt.sh 自动扫描 QQ 账号，计算 key 并自动解密。
  - export_chats.py 从数据库中导出可读文本，提供各种导出模式。
  - get_qqnt_key.sh 自动扫描 QQ 账号并计算 key。
  - sqlite_to_json.py SQLite 到 JSON 导出工具。
