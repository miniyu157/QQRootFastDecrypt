#!/bin/bash

# 为输出添加颜色
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_NC='\033[0m' # No Color

# --- 全局变量定义 (与第一个脚本对齐) ---
QQ_BASE_PATH_0="/data/user/0/com.tencent.mobileqq"
QQ_BASE_PATH_DATA="/data/data/com.tencent.mobileqq"
QQ_UID_DIR_SUFFIX="/files/uid/"
QQ_DB_DIR_SUFFIX="/databases/nt_db/nt_qq_"
QQ_BASE_PATH=""
CMD_OUTPUT_DIR="$1" # 从命令行接收可选的第一个参数

# --- 函数定义 ---

# 函数: 打印错误信息并退出
error_exit() {
    echo -e "${C_RED}[错误] $1${C_NC}" >&2
    exit 1
}

# 函数: 打印警告信息
log_warn() {
    echo -e "${C_YELLOW}[警告] $1${C_NC}"
}

# 函数: 打印信息
log_info() {
    echo -e "${C_BLUE}[信息] $1${C_NC}"
}

# 函数: 打印成功信息
log_success() {
    echo -e "${C_GREEN}[成功] $1${C_NC}"
}

# 函数: 打印重要结果 (与第一个脚本对齐)
log_result() {
    echo -e "${C_YELLOW}$1: ${C_GREEN}$2${C_NC}"
}

# 函数: 解密指定的数据库文件
# 参数1: 数据库文件名 (例如: nt_msg.db)
decrypt_database() {
    local db_name="$1"
    local db_base_name="${db_name%.db}"
    local db_source_path="${QQ_DB_FULL_PATH}/${db_name}"
    local output_db_path="${OUTPUT_DIR}/${db_name}"
    local clean_db_path="${OUTPUT_DIR}/${db_base_name}.clean.db"
    local sql_dump_path="${OUTPUT_DIR}/${db_base_name}.sql"
    local decrypted_db_path="${OUTPUT_DIR}/${db_base_name}.decrypt.db"

    echo "----------------------------------------"
    log_info "正在处理: ${C_YELLOW}${db_name}${C_NC}"

    # 0. 清理上一次运行可能残留的旧文件，防止因文件已存在而操作失败
    rm -f "$output_db_path" "$clean_db_path" "$sql_dump_path" "$decrypted_db_path"

    # 1. 检查源数据库文件是否存在
    if ! su -c "test -f '$db_source_path'" >/dev/null 2>&1; then
        log_warn "源文件 '$db_source_path' 不存在，跳过此文件。"
        return
    fi

    # 2. 复制数据库文件到输出目录
    if ! su -c "cp '$db_source_path' '$output_db_path' && chmod 666 '$output_db_path'"; then
        error_exit "复制文件 '$db_name' 失败。请检查权限。"
    fi

    # 3. 移除文件头 (前1024字节)
    tail -c +1025 "$output_db_path" > "$clean_db_path"

    # 4. 使用 sqlcipher 解密
    sqlcipher "$clean_db_path" >/dev/null <<EOF
PRAGMA key = '$final_key';
PRAGMA kdf_iter = 4000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
PRAGMA cipher_page_size = 4096;
.output "$sql_dump_path"
.dump
.exit
EOF


    # 检查 .sql 文件是否成功生成且不为空
    if [ ! -s "$sql_dump_path" ]; then
        log_warn "解密可能失败，生成的SQL文件为空。可能是Key不正确或数据库版本不兼容。"
        log_warn "将保留中间文件用于手动排查: $clean_db_path"
        rm -f "$output_db_path" # 清理原始副本
        return
    fi

    # 5. 使用转储的 SQL 文件生成无加密数据库
    cat "$sql_dump_path" | sed -e 's|^ROLLBACK;\( -- due to errors\)*$|COMMIT;|g' | sqlcipher "$decrypted_db_path"

    # 6. 清理临时文件
    rm "$output_db_path"
    rm "$clean_db_path"
    rm "$sql_dump_path"

    log_success "解密完成: ${C_GREEN}${decrypted_db_path}${C_NC}"
}


# --- 脚本主流程 ---

# 1. 环境检查
log_info "正在检查所需环境..."
if ! command -v su &> /dev/null; then
    error_exit "未找到 su 命令。此脚本需要在 Root 环境下运行 (如 Termux)。"
fi
if ! command -v sqlcipher &> /dev/null; then
    error_exit "未找到 sqlcipher 命令。请先通过 'pkg install sqlcipher' 安装它。"
fi
if ! command -v md5sum &> /dev/null; then
    error_exit "未找到 md5sum 命令。请先通过 'pkg install coreutils' 安装它。"
fi
log_success "环境检查通过。"
echo ""

# 2. 权限检查
log_info "正在检查 Root 权限..."
if ! su -c "echo 'Root check successful'" >/dev/null 2>&1; then
    error_exit "无法获取 Root 权限。请确保你的设备已经 Root 并且 Termux 已被授予 Root 权限。"
fi
log_success "Root 权限检查通过。"
echo ""

# 3. 设置输出目录
DEFAULT_OUTPUT_DIR="/storage/emulated/0/QQRootFastDecrypt"

if [ -n "$CMD_OUTPUT_DIR" ]; then
    # 如果通过命令行参数传递了路径，则直接使用
    OUTPUT_DIR="$CMD_OUTPUT_DIR"
else
    # 否则，进入交互模式
    read -p "$(echo -e ${C_BLUE}"请输入解密文件的输出目录 [默认为: ${DEFAULT_OUTPUT_DIR}]: "${C_NC})" -r -e READ_OUTPUT_DIR
    # 如果用户直接回车（输入为空），则使用默认值
    if [ -z "$READ_OUTPUT_DIR" ]; then
      OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
    else
      OUTPUT_DIR="$READ_OUTPUT_DIR"
    fi
fi

# 规范化路径：移除末尾可能存在的斜杠，防止路径拼接时出现 //
OUTPUT_DIR="${OUTPUT_DIR%/}"

# 创建目录，包括可能需要的父目录 (-p)
mkdir -p "$OUTPUT_DIR"
if [ ! -d "$OUTPUT_DIR" ]; then
    error_exit "无法创建输出目录: $OUTPUT_DIR"
fi
log_info "输出目录已设定为: ${C_YELLOW}${OUTPUT_DIR}${C_NC}"
echo ""

# 4. QQ安装路径检测
log_info "正在检测QQ数据路径..."
if su -c "test -d $QQ_BASE_PATH_0" >/dev/null 2>&1; then
    QQ_BASE_PATH=$QQ_BASE_PATH_0
elif su -c "test -d $QQ_BASE_PATH_DATA" >/dev/null 2>&1; then
    QQ_BASE_PATH=$QQ_BASE_PATH_DATA
else
    error_exit "未找到 QQ 数据目录。路径不存在: $QQ_BASE_PATH_0 或 $QQ_BASE_PATH_DATA"
fi
log_success "检测到QQ数据路径: $QQ_BASE_PATH"

# 5. 获取并解析QQ账号列表
QQ_UID_DIR="${QQ_BASE_PATH}${QQ_UID_DIR_SUFFIX}"
uid_files_raw=$(su -c "ls -1 '$QQ_UID_DIR'" 2>/dev/null)
if [ -z "$uid_files_raw" ]; then
    error_exit "在目录 '$QQ_UID_DIR' 中未找到任何QQ账号信息文件。"
fi

declare -a qq_numbers
declare -a uids
while IFS= read -r line; do
    if [[ "$line" == *"###"* ]]; then
        qq_numbers+=("$(echo "$line" | awk -F'###' '{print $1}')")
        uids+=("$(echo "$line" | awk -F'###' '{print $2}')")
    fi
done <<< "$uid_files_raw"

if [ ${#qq_numbers[@]} -eq 0 ]; then
    error_exit "解析失败，未找到格式为 '{qq}###{uid}' 的文件。"
fi

# 6. 用户选择账号
echo "----------------------------------------"
log_info "发现以下QQ账号，请选择要计算的账号："
for i in "${!qq_numbers[@]}"; do
    echo -e "  ${C_YELLOW}[$((i+1))]${C_NC} ${qq_numbers[$i]}"
done
echo "----------------------------------------"
read -p "请输入选项编号: " choice
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#qq_numbers[@]} ]; then
    error_exit "无效的输入。"
fi

selected_index=$((choice-1))
selected_qq="${qq_numbers[$selected_index]}"
selected_uid="${uids[$selected_index]}"

echo ""
log_info "正在获取密钥..."

# 7. 计算密钥所需的值
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
rand_raw=$(su -c "strings '$DB_PATH' | grep -E -A 1 'QQ_NT DB\$?' | tail -n 1")
rand=$(echo -n "$rand_raw" | sed 's/[^a-zA-Z0-9]//g')

# f. 校验提取到的 `rand` 值是否为空或长度不等于8
if [ -z "$rand" ] || [ ${#rand} -ne 8 ]; then
    error_exit "提取 rand 失败或提取到的值 '$rand' 格式不正确。"
fi

# g. 拼接 UID 的哈希值和 rand，计算最终的密钥
key_input="${QQ_UID_hash}${rand}"
final_key=$(echo -n "$key_input" | md5sum | cut -d' ' -f1)

log_success "key: $final_key"

# --- 解密数据库 ---

# 定义数据库源目录
QQ_DB_FULL_PATH="${QQ_BASE_PATH}${QQ_DB_DIR_SUFFIX}${QQ_path_hash}"

# 使用函数解密数据库
decrypt_database "nt_msg.db"
decrypt_database "profile_info.db"

echo "========================================"
log_success "所有任务已完成！"
log_info "解密后的文件位于目录: ${C_GREEN}${OUTPUT_DIR}${C_NC}"
echo "========================================"

