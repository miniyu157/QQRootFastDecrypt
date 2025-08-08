#!/bin/bash

# 为输出添加颜色
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_NC='\033[0m' # No Color

# --- 全局变量定义 ---
QQ_BASE_PATH=""
CMD_OUTPUT_DIR="$1"

# --- 函数定义 (无变动) ---
error_exit() { echo -e "${C_RED}[错误] $1${C_NC}" >&2; exit 1; }
log_warn() { echo -e "${C_YELLOW}[警告] $1${C_NC}"; }
log_info() { echo -e "${C_BLUE}[信息] $1${C_NC}"; }
log_success() { echo -e "${C_GREEN}[成功] $1${C_NC}"; }
log_result() { echo -e "${C_YELLOW}$1: ${C_GREEN}$2${C_NC}"; }

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
    rm -f "$output_db_path" "$clean_db_path" "$sql_dump_path" "$decrypted_db_path"
    if ! su -c "test -f '$db_source_path'" >/dev/null 2>&1; then
        log_warn "源文件 '$db_source_path' 不存在，跳过此文件。"
        return
    fi
    if ! su -c "cp '$db_source_path' '$output_db_path' && chmod 666 '$output_db_path'"; then
        error_exit "复制文件 '$db_name' 失败。请检查权限。"
    fi
    tail -c +1025 "$output_db_path" > "$clean_db_path"
    sqlcipher "$clean_db_path" >/dev/null <<EOF
PRAGMA key = '$final_key';
PRAGMA kdf_iter = 4000;
PRAGMA cipher_hmac_algorithm = HMAC_SHA1;
PRAGMA cipher_page_size = 4096;
.output "$sql_dump_path"
.dump
.exit
EOF
    if [ ! -s "$sql_dump_path" ]; then
        log_warn "解密可能失败，生成的SQL文件为空。可能是Key不正确或数据库版本不兼容。"
        log_warn "将保留中间文件用于手动排查: $clean_db_path"
        rm -f "$output_db_path"
        return
    fi
    cat "$sql_dump_path" | sed -e 's|^ROLLBACK;\( -- due to errors\)*$|COMMIT;|g' | sqlcipher "$decrypted_db_path"
    rm "$output_db_path" "$clean_db_path" "$sql_dump_path"
    log_success "解密完成: ${C_GREEN}${decrypted_db_path}${C_NC}"
}

# --- 脚本主流程 ---

# 1. 环境与权限检查 (无变动)
log_info "正在检查所需环境..."
if ! command -v su &> /dev/null; then error_exit "未找到 su 命令。此脚本需要在 Root 环境下运行。"; fi
if ! command -v sqlcipher &> /dev/null; then error_exit "未找到 sqlcipher 命令。请先通过 'pkg install sqlcipher' 安装它。"; fi
if ! command -v md5sum &> /dev/null; then error_exit "未找到 md5sum 命令。请先通过 'pkg install coreutils' 安装它。"; fi
log_success "环境检查通过。"
echo ""
log_info "正在检查 Root 权限..."
if ! su -c "echo 'Root check successful'" >/dev/null 2>&1; then error_exit "无法获取 Root 权限。"; fi
log_success "Root 权限检查通过。"
echo ""

# 2. 设置输出目录 (无变动)
DEFAULT_OUTPUT_DIR="/storage/emulated/0/QQRootFastDecrypt"
if [ -n "$CMD_OUTPUT_DIR" ]; then
    OUTPUT_DIR="$CMD_OUTPUT_DIR"
else
    read -p "$(echo -e ${C_BLUE}"请输入解密文件的输出目录 [默认为: ${DEFAULT_OUTPUT_DIR}]: "${C_NC})" -r -e READ_OUTPUT_DIR
    if [ -z "$READ_OUTPUT_DIR" ]; then OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"; else OUTPUT_DIR="$READ_OUTPUT_DIR"; fi
fi
OUTPUT_DIR="${OUTPUT_DIR%/}"
mkdir -p "$OUTPUT_DIR"
if [ ! -d "$OUTPUT_DIR" ]; then error_exit "无法创建输出目录: $OUTPUT_DIR"; fi
log_info "输出目录已设定为: ${C_YELLOW}${OUTPUT_DIR}${C_NC}"
echo ""

# 3. 扫描并处理QQ安装实例 (无变动)
log_info "正在扫描QQ安装实例..."
QQ_PACKAGE_NAME="com.tencent.mobileqq"
declare -A seen_user_ids
declare -a final_paths
declare -a final_labels
all_qq_paths_raw=$(su -c "find /data/user /data -maxdepth 2 -type d -name $QQ_PACKAGE_NAME 2>/dev/null" | sort)
while IFS= read -r path; do
    if [[ $path =~ /user/([0-9]+)/ ]]; then
        user_id="${BASH_REMATCH[1]}"
        if [[ -z "${seen_user_ids[$user_id]}" ]]; then
            final_paths+=("$path")
            final_labels+=("用户 $user_id")
            seen_user_ids[$user_id]=1
        fi
    fi
done <<< "$all_qq_paths_raw"
while IFS= read -r path; do
    if [[ $path == "/data/data/$QQ_PACKAGE_NAME" ]]; then
        if [[ -z "${seen_user_ids[0]}" ]]; then
            final_paths+=("$path")
            final_labels+=("用户 0")
            seen_user_ids[0]=1
        fi
    fi
done <<< "$all_qq_paths_raw"
case ${#final_paths[@]} in
0)
    error_exit "未在系统中找到任何QQ安装目录。请确认QQ已安装。"
    ;;
1)
    log_info "发现唯一QQ实例，已自动选择。"
    QQ_BASE_PATH="${final_paths[0]}"
    SELECTED_LABEL="${final_labels[0]}"
    ;;
*)
    echo "----------------------------------------"
    log_info "发现以下QQ安装实例，请选择要操作的一个："
    for i in "${!final_paths[@]}"; do
        echo -e "  ${C_YELLOW}[$((i+1))]${C_NC} [${final_labels[$i]}] (${final_paths[$i]})"
    done
    echo "----------------------------------------"
    read -p "请输入选项编号: " choice
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#final_paths[@]} ]; then
        error_exit "无效的输入。"
    fi
    selected_index=$((choice-1))
    QQ_BASE_PATH="${final_paths[$selected_index]}"
    SELECTED_LABEL="${final_labels[$selected_index]}"
    log_success "已选择: ${SELECTED_LABEL}"
    ;;
esac

# =========== 从这里开始是本次的修改 ===========

# 4. 获取并解析QQ账号列表
QQ_UID_DIR_SUFFIX="/files/uid/"
QQ_UID_DIR="${QQ_BASE_PATH}${QQ_UID_DIR_SUFFIX}"
uid_files_raw=$(su -c "ls -1 '$QQ_UID_DIR'" 2>/dev/null)
if [ -z "$uid_files_raw" ]; then
    error_exit "在目录 '$QQ_UID_DIR' 中未找到任何QQ账号信息文件。"
fi

declare -a qq_numbers
declare -a uids
# 使用纯Bash进行字符串分割，替换awk，以提高效率和稳定性
while IFS= read -r line; do
    # 检查行中是否包含分隔符 '###'
    if [[ "$line" == *"###"* ]]; then
        # 使用参数扩展来分割字符串
        qq="${line%%###*}"
        uid="${line#*###}"
        qq_numbers+=("$qq")
        uids+=("$uid")
    fi
done <<< "$uid_files_raw"

if [ ${#qq_numbers[@]} -eq 0 ]; then
    error_exit "解析失败，在 '$QQ_UID_DIR' 未找到格式为 '{qq}###{uid}' 的文件。"
fi

# =========== 修改结束 ===========

# 5. 用户选择账号 (无变动)
echo ""
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

# 6. 计算密钥 (无变动)
echo ""
log_info "正在获取密钥..."
QQ_DB_DIR_SUFFIX="/databases/nt_db/nt_qq_"
QQ_UID_hash=$(echo -n "$selected_uid" | md5sum | cut -d' ' -f1)
QQ_path_hash_input="${QQ_UID_hash}nt_kernel"
QQ_path_hash=$(echo -n "$QQ_path_hash_input" | md5sum | cut -d' ' -f1)
DB_PATH="${QQ_BASE_PATH}${QQ_DB_DIR_SUFFIX}${QQ_path_hash}/nt_msg.db"
if ! su -c "test -f '$DB_PATH'" >/dev/null 2>&1; then
    error_exit "数据库文件 'nt_msg.db' 不存在！请确认该QQ账号是否已正常登录并生成了消息数据库。"
fi
rand_raw=$(su -c "strings '$DB_PATH' | grep -E -A 1 'QQ_NT DB\$?' | tail -n 1")
rand=$(echo -n "$rand_raw" | sed 's/[^a-zA-Z0-9]//g')
if [ -z "$rand" ] || [ ${#rand} -ne 8 ]; then
    error_exit "提取 rand 失败或提取到的值 '$rand' 格式不正确。"
fi
key_input="${QQ_UID_hash}${rand}"
final_key=$(echo -n "$key_input" | md5sum | cut -d' ' -f1)
log_success "key: $final_key"

# 7. 解密数据库 (无变动)
QQ_DB_FULL_PATH="${QQ_BASE_PATH}${QQ_DB_DIR_SUFFIX}${QQ_path_hash}"
decrypt_database "nt_msg.db"
decrypt_database "profile_info.db"

echo "========================================"
log_success "所有任务已完成！"
log_info "解密后的文件位于目录: ${C_GREEN}${OUTPUT_DIR}${C_NC}"
echo "========================================"