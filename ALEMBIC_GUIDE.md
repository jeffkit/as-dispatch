# Alembic 数据库迁移指南

本文档说明如何使用 Alembic 管理 Forward Service 的数据库迁移。

## 什么是 Alembic？

Alembic 是 SQLAlchemy 官方推荐的数据库迁移工具，提供：

- **版本管理**: 每次数据库结构变更都有版本号记录
- **可回滚**: 支持升级和降级
- **自动生成**: 自动检测模型变化并生成迁移脚本
- **数据安全**: 迁移脚本可包含数据迁移逻辑

## 目录结构

```
packages/forward-service/
├── alembic.ini                    # Alembic 配置文件
├── alembic/
│   ├── env.py                     # 迁移环境配置
│   ├── script.py.mako             # 迁移脚本模板
│   └── versions/                  # 迁移脚本目录
│       └── 8d6e2b7af5d7_init_创建初始数据库表结构.py
└── ALEMBIC_GUIDE.md               # 本文档
```

## 常用命令

### 1. 查看当前迁移状态

```bash
# 查看当前数据库版本
alembic current

# 查看迁移历史
alembic history

# 查看待执行的迁移
alembic heads
```

### 2. 生成新的迁移脚本

当你修改了 `models.py` 中的模型定义后，需要生成对应的迁移脚本：

```bash
# 自动生成迁移（推荐）
alembic revision --autogenerate -m "描述你的变更"

# 示例：添加新列
alembic revision --autogenerate -m "add user avatar field"
```

**生成后请检查**：
- `alembic/versions/` 下新生成的 `.py` 文件
- 确认 `upgrade()` 和 `downgrade()` 函数是否符合预期

### 3. 执行迁移

```bash
# 升级到最新版本
alembic upgrade head

# 升级到指定版本
alembic upgrade <revision_id>

# 回退一个版本
alembic downgrade -1

# 回退到指定版本
alembic downgrade <revision_id>

# 回退到空（删除所有表）
alembic downgrade base
```

### 4. 其他实用命令

```bash
# 离线模式生成 SQL（不执行）
alembic upgrade head --sql

# 查看迁移 SQL（不执行）
alembic upgrade head --sql > migration.sql

# 标记特定版本（不实际执行迁移）
alembic stamp <revision_id>
```

## 工作流程

### 开发新功能时的数据库变更流程

1. **修改模型定义**
   ```python
   # forward_service/models.py
   class Chatbot(Base):
       # ... 现有字段 ...
       avatar_url: Mapped[Optional[str]] = mapped_column(
           String(500),
           nullable=True,
           comment="头像 URL"
       )
   ```

2. **生成迁移脚本**
   ```bash
   alembic revision --autogenerate -m "add avatar_url to chatbots"
   ```

3. **检查生成的迁移**
   ```python
   # alembic/versions/xxxxx_add_avatar_url_to_chatbots.py
   def upgrade():
       op.add_column('chatbots', sa.Column('avatar_url', sa.String(length=500), nullable=True))

   def downgrade():
       op.drop_column('chatbots', 'avatar_url')
   ```

4. **执行迁移**
   ```bash
   # 本地开发环境
   alembic upgrade head
   ```

5. **提交代码**
   ```bash
   git add alembic/versions/xxxxx_add_avatar_url_to_chatbots.py
   git commit -m "feat: add avatar_url field to chatbots table"
   ```

### 生产环境部署流程

1. **准备阶段**
   ```bash
   # 生成迁移 SQL 供审查
   alembic upgrade head --sql > migration.sql

   # 发送给 DBA 或团队成员审查
   ```

2. **备份数据库（生产环境必须）**
   ```bash
   # SQLite
   cp data/forward_service.db data/forward_service.db.backup

   # MySQL
   mysqldump -u user -p database_name > backup.sql
   ```

3. **执行迁移**
   ```bash
   # 方式 1: 直接执行（适用于可信环境）
   alembic upgrade head

   # 方式 2: 执行审查过的 SQL
   mysql -u user -p database_name < migration.sql
   ```

4. **验证**
   ```bash
   # 检查当前版本
   alembic current

   # 检查表结构
   sqlite3 data/forward_service.db ".schema chatbots"
   ```

## 环境变量配置

Alembic 会自动读取以下环境变量：

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `DATABASE_URL` | 数据库连接 URL | `sqlite:///./data/forward_service.db` |

**示例**：

```bash
# SQLite（开发环境）
export DATABASE_URL="sqlite+aiosqlite:///./data/forward_service.db"

# MySQL（生产环境）
export DATABASE_URL="mysql+aiomysql://user:password@host:port/database"

# 执行迁移时会自动转换为同步 URL
alembic upgrade head
```

## 数据库 URL 说明

注意 Alembic 使用**同步引擎**，而应用使用**异步引擎**：

| 用途 | SQLite URL | MySQL URL |
|------|-----------|-----------|
| 应用运行时 | `sqlite+aiosqlite:///...` | `mysql+aiomysql://...` |
| Alembic 迁移 | `sqlite:///...` | `mysql+pymysql://...` |

`env.py` 会自动处理 URL 转换，无需手动修改。

## 手动编写迁移

对于复杂的数据迁移，`autogenerate` 可能无法完全满足需求，需要手动编写：

```python
# alembic/versions/xxxxx_manual_migration.py

def upgrade():
    # 1. 修改表结构
    op.add_column('chatbots', sa.Column('status', sa.String(20), nullable=True))

    # 2. 数据迁移（使用原始 SQL）
    op.execute("""
        UPDATE chatbots
        SET status = 'active'
        WHERE enabled = 1
    """)

    # 3. 修改列约束
    op.alter_column('chatbots', 'status', nullable=False)

def downgrade():
    # 回滚操作
    op.drop_column('chatbots', 'status')
```

## 常见问题

### Q1: 迁移失败怎么办？

```bash
# 1. 查看当前版本
alembic current

# 2. 回退到上一个版本
alembic downgrade -1

# 3. 修复迁移脚本中的问题

# 4. 重新执行
alembic upgrade head
```

### Q2: 如何处理已存在的数据库？

```bash
# 方式 1: 标记当前版本（不执行迁移）
alembic stamp head

# 方式 2: 生成迁移并手动检查
alembic revision --autogenerate -m "check existing database"
# 然后手动编辑迁移脚本，只保留缺失的部分
```

### Q3: 多个开发者如何协作？

- **不要修改已发布的迁移脚本**
- 新的迁移基于最新的 `head` 创建
- 如果产生冲突，协商后重新生成迁移

### Q4: 如何在生产环境安全迁移？

```bash
# 1. 先在测试环境验证
alembic upgrade head

# 2. 生成 SQL 供审查
alembic upgrade head --sql > migration.sql

# 3. 备份生产数据库

# 4. 在低峰期执行迁移
alembic upgrade head

# 5. 验证应用功能
```

## 最佳实践

1. **迁移脚本要可回滚**
   - `downgrade()` 函数必须正确实现
   - 避免使用不可逆操作（如删除列时先备份数据）

2. **小步快跑**
   - 每次迁移只做一件事
   - 避免在单个迁移中做太多变更

3. **测试迁移**
   - 在开发环境先执行 `upgrade` 和 `downgrade`
   - 确保可以安全回滚

4. **数据备份**
   - 生产环境迁移前务必备份数据库
   - 重要变更先在测试环境验证

5. **版本命名**
   - 使用清晰的描述信息
   - 格式：`action: description`
   - 示例：`"add user avatar field"`, `"rename column old_name to new_name"`

## 相关文档

- [Alembic 官方文档](https://alembic.sqlalchemy.org/)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- 项目主文档: `CLAUDE.md`
- 数据库实现总结: `DATABASE_SUMMARY.md`

## 迁移历史

| 版本 | 日期 | 描述 |
|------|------|------|
| `8d6e2b7af5d7` | 2026-01-11 | 创建初始数据库表结构（chatbots, chat_access_rules, user_sessions, forward_logs, processing_sessions, system_config） |
