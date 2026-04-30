# 迁移指南

## 从旧版本迁移到重构版

### 1. 环境配置

旧版本使用硬编码配置，新版本使用环境变量：

```bash
# 设置环境变量
export DASHSCOPE_API_KEY="your_api_key_here"

# 或创建 .env 文件（推荐）
cp config/.env.example .env
# 编辑 .env 文件填入你的 API Key
```

### 2. 文件结构变化

| 旧版本 | 新版本 | 说明 |
|--------|--------|------|
| `claw.py` | `main.py` | 主入口文件 |
| `Agent.md` | `Agent.md` | 保持不变 |
| `skills/calculator/calculator.md` | `skills/calculator/calculator.md` | 保持不变 |

### 3. 运行方式

```bash
# 旧版本
python claw.py

# 新版本
python main.py
```

### 4. 功能对比

所有原有功能保持不变：
- ✅ 系统命令执行
- ✅ 技能调用
- ✅ 直接回答
- ✅ 对话循环

新增功能：
- ✅ 环境变量配置
- ✅ 命令安全检查
- ✅ 超时保护
- ✅ 更好的错误处理

### 5. 兼容性说明

- 所有现有的技能文件无需修改
- Agent.md 提示词无需修改
- 用户交互方式完全相同

### 6. 验证迁移

运行以下命令测试：

```bash
# 测试基本功能
python main.py

# 在交互界面测试
User: 查看当前目录
User: 调用 calculator skill 计算 2+3*4
User: Python 如何定义函数？
```

### 7. 回退方案

如果遇到问题，可以继续使用旧版本：

```bash
python claw.py
```

新旧版本可以共存，互不影响。
