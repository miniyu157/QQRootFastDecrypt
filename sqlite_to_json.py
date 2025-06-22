#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import warnings

warnings.filterwarnings("ignore", category=UserWarning)

import sqlite3
import json
import base64
import traceback
import argparse
import os

# 尝试导入 blackboxprotobuf，如果失败则给出提示
try:
    import blackboxprotobuf
except ImportError:
    print("错误: 依赖库 'blackboxprotobuf' 未安装。")
    print("请运行: pip install blackboxprotobuf")
    exit(1)


def recursively_process_object(obj):
    if isinstance(obj, dict):
        return {k: recursively_process_object(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [recursively_process_object(item) for item in obj]
    if isinstance(obj, bytes):
        try:
            # 优先尝试作为 Protobuf 解码
            decoded_data, _ = blackboxprotobuf.decode_message(obj)
            return recursively_process_object(decoded_data)
        except Exception:
            # 如果 Protobuf 解码失败, 再尝试作为 UTF-8 字符串解码
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                # 如果连 UTF-8 解码也失败, 最后才转为 Base64
                return base64.b64encode(obj).decode("utf-8")
    return obj


def export_table_to_json(
    db_path, table_name, json_path, enable_columns=None, ignore_columns=None
):
    conn = None
    enable_columns = enable_columns or []
    ignore_columns = ignore_columns or []
    try:
        if not os.path.exists(db_path):
            print(f"错误: 数据库文件不存在 '{db_path}'")
            return
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        print(f"成功以只读模式连接到数据库: {db_path}")
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if cursor.fetchone() is None:
            print(f"错误: 在数据库中未找到表 '{table_name}'")
            return
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        print(f"从表 '{table_name}' 中查询到 {len(rows)} 行数据。")
        if not rows:
            print("表中没有数据，生成空的 JSON 文件。")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return
        original_columns = rows[0].keys()
        final_columns = []
        if enable_columns:
            final_columns = [col for col in original_columns if col in enable_columns]
            print(f"白名单模式已启用。将只导出列: {final_columns}")
        elif ignore_columns:
            final_columns = [
                col for col in original_columns if col not in ignore_columns
            ]
            print(f"黑名单模式已启用。将忽略列: {ignore_columns}")
        else:
            final_columns = list(original_columns)
            print("默认模式，将导出所有列。")
        processed_data_list = [{key: row[key] for key in final_columns} for row in rows]
        fully_processed_data = recursively_process_object(processed_data_list)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(fully_processed_data, f, ensure_ascii=False, indent=4)
        print(f"数据已成功导出到: {json_path}")
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
    except Exception as e:
        print(f"发生未知错误: {e}")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
            print("数据库连接已关闭。")


def main():
    parser = argparse.ArgumentParser(description="SQLite 到 JSON 导出工具")
    parser.add_argument("db_path", help="源 SQLite 数据库文件的路径")
    parser.add_argument("table_name", help="数据库中要导出的表名")
    parser.add_argument(
        "-o", "--output", help="输出的 JSON 文件路径 (可选, 默认将根据输入自动生成)"
    )
    column_group = parser.add_mutually_exclusive_group()
    column_group.add_argument(
        "-e",
        "--enable",
        nargs="+",
        help="[白名单模式] 只导出指定的列，可提供多个列名，用空格分隔。",
    )
    column_group.add_argument(
        "-i",
        "--ignore",
        nargs="+",
        help="[黑名单模式] 导出时忽略指定的列，可提供多个列名，用空格分隔。",
    )
    args = parser.parse_args()
    if args.output:
        json_path = args.output
    else:
        db_basename = os.path.splitext(os.path.basename(args.db_path))[0]
        json_path = f"{db_basename}.{args.table_name}.json"
    export_table_to_json(
        db_path=args.db_path,
        table_name=args.table_name,
        json_path=json_path,
        enable_columns=args.enable,
        ignore_columns=args.ignore,
    )


if __name__ == "__main__":
    main()
