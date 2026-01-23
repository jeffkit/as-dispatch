#!/usr/bin/env python3
"""
数据迁移脚本：将 url_template + agent_id 合并为 target_url

用法：
    python scripts/migrate_target_url.py [database_path]
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str):
    """执行数据迁移"""
    print(f"开始迁移数据库: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表结构
    cursor.execute("PRAGMA table_info(chatbots)")
    columns = {row[1]: row for row in cursor.fetchall()}
    
    print(f"当前列: {list(columns.keys())}")
    
    # 检查是否存在 target_url 列
    if "target_url" not in columns:
        print("添加 target_url 列...")
        cursor.execute("ALTER TABLE chatbots ADD COLUMN target_url TEXT DEFAULT ''")
        conn.commit()
        print("  ✅ 已添加 target_url 列")
    else:
        print("  ℹ️ target_url 列已存在")
    
    # 迁移数据：从 url_template + agent_id 生成 target_url
    print("\n迁移数据...")
    cursor.execute("SELECT id, name, url_template, agent_id, target_url FROM chatbots")
    rows = cursor.fetchall()
    
    migrated = 0
    skipped = 0
    for row in rows:
        bot_id, name, url_template, agent_id, target_url = row
        
        # 如果 target_url 已经有值，跳过
        if target_url:
            print(f"  ⏭️ {name}: target_url 已存在 ({target_url[:50]}...)")
            skipped += 1
            continue
        
        # 从 url_template 和 agent_id 生成 target_url
        if url_template:
            new_target_url = url_template.replace("{agent_id}", agent_id or "")
            cursor.execute(
                "UPDATE chatbots SET target_url = ? WHERE id = ?",
                (new_target_url, bot_id)
            )
            print(f"  ✅ {name}: {new_target_url}")
            migrated += 1
        else:
            print(f"  ⚠️ {name}: 无 url_template，跳过")
            skipped += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n迁移完成！")
    print(f"  - 更新: {migrated} 个")
    print(f"  - 跳过: {skipped} 个")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # 默认路径
        default_paths = [
            Path(__file__).parent.parent / "data" / "forward_service.db",
            Path("/data/projects/as-dispatch/data/forward_service.db")
        ]
        
        db_path = None
        for path in default_paths:
            if path.exists():
                db_path = str(path)
                break
        
        if not db_path:
            print("错误: 未找到数据库文件")
            print("用法: python scripts/migrate_target_url.py <database_path>")
            sys.exit(1)
    
    migrate(db_path)
