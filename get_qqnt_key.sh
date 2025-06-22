#!/bin/bash

# --- 全局变量定义 ---

# 定义用于在终端输出中显示不同颜色的ANSI转义序列
C_RED='\033[0;31m'       # 红色，用于错误信息
C_GREEN='\033[0;32m'     # 绿色，用于成功信息
C_YELLOW='\033[0;33m'    # 黄色，用于结果展示
C_BLUE='\033[0;34m'      # 蓝色，用于提示信息
C_NC='\033[0m'           # 无颜色，用于重置终端颜色

# 定义两个可能的QQ数据存储基础路径
QQ_BASE_PATH_0="/data/user/0/com.tencent.mobileqq"
QQ_BASE_PATH_DATA="/data/data/com.tencent.mobileqq"

# 定义QQ账号信息文件和数据库文件所在的相对路径后缀
QQ_UID_DIR_SUFFIX="/files/uid/"
QQ_DB_DIR_SUFFIX="/databases/nt_db/nt_qq_"

# 初始化QQ基础路径变量，后续脚本会检测并设置正确的路径
QQ_BASE_PATH=""

# --- 函数定义 ---

# 错误处理函数：打印红色错误信息并退出脚本
# 参数 $1: 要显示的错误信息字符串
error_exit() {
    echo -e "${C_RED}[错误] $1${C_NC}" >&2 # >&2 表示将输出重定向到标准错误
    exit 1
}

# 信息日志函数：打印蓝色提示信息
# 参数 $1: 要显示的信息字符串
log_info() {
    echo -e "${C_BLUE}[信息] $1${C_NC}"
}

# 成功日志函数：打印绿色成功信息
# 参数 $1: 要显示的成功信息字符串
log_success() {
    echo -e "${C_GREEN}[成功] $1${C_NC}"
}

# 结果显示函数：以 "标签: 值" 的格式打印黄绿色的结果
# 参数 $1: 结果的标签
# 参数 $2: 结果的值
log_result() {
    echo -e "${C_YELLOW}$1: ${C_GREEN}$2${C_NC}"
}


# --- 主逻辑开始 ---

# 1. 权限检查
# 尝试以 root 权限执行一个简单的命令，检查是否能成功获取 root 权限
if ! su -c "echo 'Root check successful'" >/dev/null 2>&1; then
    error_exit "无法获取 root 权限。请确保你的设备已经 root 并且 Termux 已被授予 root 权限。"
fi

# 2. QQ安装路径检测
# 检查两个常见的QQ数据目录是否存在，并设置 QQ_BASE_PATH 变量
if su -c "test -d $QQ_BASE_PATH_0" >/dev/null 2>&1; then
    QQ_BASE_PATH=$QQ_BASE_PATH_0
elif su -c "test -d $QQ_BASE_PATH_DATA" >/dev/null 2>&1; then
    QQ_BASE_PATH=$QQ_BASE_PATH_DATA
else
    # 如果两个路径都不存在，则报错退出
    error_exit "未找到 QQ 数据目录。路径不存在: $QQ_BASE_PATH_0 或 $QQ_BASE_PATH_DATA"
fi

# 3. 获取并解析QQ账号列表
# 拼接出存放账号信息文件的完整目录路径
QQ_UID_DIR="${QQ_BASE_PATH}${QQ_UID_DIR_SUFFIX}"

# 以 root 权限列出该目录下的所有文件
# 2>/dev/null 表示忽略可能出现的错误信息
uid_files_raw=$(su -c "ls -1 '$QQ_UID_DIR'" 2>/dev/null)

# 检查是否成功获取到文件列表
if [ -z "$uid_files_raw" ]; then
    error_exit "在目录 '$QQ_UID_DIR' 中未找到任何QQ账号信息文件。"
fi

# 声明两个数组，分别用于存储解析出的 QQ号 和对应的 UID
declare -a qq_numbers
declare -a uids

# 逐行读取文件列表，并解析出QQ号和UID
# 文件名格式为 "{qq}###{uid}"
while IFS= read -r line; do
    if [[ "$line" == *"###"* ]]; then
        # 使用 awk 以 "###" 为分隔符，提取第一部分（QQ号）和第二部分（UID）
        qq_numbers+=("$(echo "$line" | awk -F'###' '{print $1}')")
        uids+=("$(echo "$line" | awk -F'###' '{print $2}')")
    fi
done <<< "$uid_files_raw" # <<< 表示使用这里的字符串作为 while 循环的输入

# 检查是否成功解析到任何账号
if [ ${#qq_numbers[@]} -eq 0 ]; then
    error_exit "解析失败，未找到格式为 '{qq}###{uid}' 的文件。"
fi

# 4. 用户选择账号
# 打印所有找到的QQ账号，让用户选择
echo "----------------------------------------"
log_info "发现以下QQ账号，请选择要计算的账号："
for i in "${!qq_numbers[@]}"; do
    echo -e "  ${C_YELLOW}[$((i+1))]${C_NC} ${qq_numbers[$i]}"
done
echo "----------------------------------------"

# 读取用户输入
read -p "请输入选项编号: " choice

# 校验用户输入是否为有效的数字选项
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#qq_numbers[@]} ]; then
    error_exit "无效的输入。"
fi

# 根据用户的选择，设置要处理的目标QQ号和UID
selected_index=$((choice-1)) # 数组索引从0开始，所以需要减1
selected_qq="${qq_numbers[$selected_index]}"
selected_uid="${uids[$selected_index]}"

echo ""
log_info "正在处理..."

# 5. 计算密钥所需的值
# a. 计算 QQ UID 的 MD5 哈希值
QQ_UID_hash=$(echo -n "$selected_uid" | md5sum | cut -d' ' -f1)

# b. 拼接字符串并计算第二次 MD5 哈希，用于构成数据库路径
QQ_path_hash_input="${QQ_UID_hash}nt_kernel"
QQ_path_hash=$(echo -n "$QQ_path_hash_input" | md5sum | cut -d' ' -f1)

# c. 拼接出最终的数据库文件（nt_msg.db）的完整路径
DB_PATH="${QQ_BASE_PATH}${QQ_DB_DIR_SUFFIX}${QQ_path_hash}/nt_msg.db"

# d. 检查数据库文件是否存在
if ! su -c "test -f '$DB_PATH'" >/dev/null 2>&1; then
    error_exit "数据库文件 'nt_msg.db' 不存在！请确认该QQ账号是否已正常登录并生成了消息数据库。"
fi

# e. 从数据库文件中提取 `rand` 值
# `strings` 命令可以提取文件中的可打印字符
# `grep` 查找包含 "QQ_NT DB" 的行，并返回其后一行 (-A 1)
# `tail -n 1` 取最后一行，即我们需要的那一行
# `sed` 移除非字母和数字的字符，进行清理
rand_raw=$(su -c "strings '$DB_PATH' | grep -E -A 1 'QQ_NT DB\$?' | tail -n 1")
rand=$(echo -n "$rand_raw" | sed 's/[^a-zA-Z0-9]//g')

# f. 校验提取到的 `rand` 值是否为空或长度不等于8
if [ -z "$rand" ] || [ ${#rand} -ne 8 ]; then
    error_exit "提取 rand 失败或提取到的值 '$rand' 格式不正确。"
fi

# g. 拼接 UID 的哈希值和 rand，计算最终的密钥
key_input="${QQ_UID_hash}${rand}"
final_key=$(echo -n "$key_input" | md5sum | cut -d' ' -f1)

# 6. 打印结果
echo "========================================"
echo -e "${C_GREEN}          计算完成 - 结果如下          ${C_NC}"
echo "========================================"
log_result "QQ" "$selected_qq"
log_result "UID" "$selected_uid"
log_result "QQ_UID_hash" "$QQ_UID_hash"
log_result "QQ_path_hash" "$QQ_path_hash"
log_result "rand" "$rand"
log_result "key" "$final_key"
echo "========================================"
