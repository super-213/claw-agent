# 树莓派部署

需要使用自己的域名从外网访问时，在完成本页部署后继续阅读
[树莓派安装 Cloudflare Tunnel 并绑定自定义域名](CLOUDFLARE_TUNNEL.md)。

本机在项目根目录运行 `./package-pi.sh`。脚本会在需要时安装前端依赖、构建 React，再生成
`release/claw-agent-pi.tar.gz`。压缩包包含后端源码、前端构建产物、技能和部署脚本；
不包含 `.env`、`.data`、`files`、日志、虚拟环境或 `node_modules`。

把压缩包传到树莓派（替换用户名和地址）：

```bash
scp release/claw-agent-pi.tar.gz pi@192.168.1.100:~/
```

在树莓派上执行：

```bash
tar -xzf ~/claw-agent-pi.tar.gz -C ~
cd ~/claw-agent
bash deploy/pi-start.sh
```

首次运行会在树莓派安装 Python 依赖和缺少的 Nginx/Python venv 系统包，
并要求输入 DashScope API Key；因此首次运行需要联网。后续更新使用下方的
`claw-agent-new` 流程。脚本保留树莓派已有的 `.env`、`.data` 和 `files`，
在 systemd 中启动后端，在 Nginx 的
80 端口提供前端并转发 API。已有其他 Nginx 站点时脚本会停止，避免覆盖。
Nginx 的源配置在 `deploy/claw-agent.conf`。`pi-nginx.sh` 比较它与
`/etc/nginx/sites-available/claw-agent` 的内容，仅在变化时更新配置并重载 Nginx；
`pi-start.sh` 会调用它，也可以单独运行 `bash deploy/pi-nginx.sh`。
配置变化时脚本会运行 `nginx -t`，校验失败则恢复原配置。

检查服务：

```bash
sudo systemctl status claw-agent nginx
sudo journalctl -u claw-agent -n 80 --no-pager
```

日常管理：

```bash
bash ~/claw-agent/deploy/pi-status.sh
bash ~/claw-agent/deploy/pi-stop.sh
bash ~/claw-agent/deploy/pi-start.sh
bash ~/claw-agent/deploy/pi-nginx.sh
```

更新时，在树莓派把新包解压到 `~/claw-agent-new`，再运行新版本里的更新脚本：

```bash
mkdir -p ~/claw-agent-new
tar -xzf ~/claw-agent-pi.tar.gz --strip-components=1 -C ~/claw-agent-new
bash ~/claw-agent-new/deploy/pi-update.sh
```

更新脚本将旧代码移到带时间戳的备份目录，把新代码移动到 `~/claw-agent`，
迁移 `.env`、`.data`、`files`、`.venv`、日志及已有自定义技能，随后运行
`pi-start.sh` 并检查服务。如果新版本启动失败，脚本会尝试恢复旧目录并重启旧服务。

注意：本机是 macOS 时，Python 虚拟环境不能打包后在树莓派 Linux ARM 上直接运行。
前端构建产物可以跨平台复制，Python 依赖必须在树莓派上安装。


## 011 生活资料与记忆

资料与记忆首次使用时创建在 `HOME_DATA_DIR/knowledge/`，包含 `knowledge.json`、锁文件、日内元数据备份与 `blobs/` 原文件副本。部署更新继续保留整个 `.data` 和 `files`；自定义家庭目录也必须一起备份。无需迁移旧事项和旧工作记忆，新资料由用户明确保存。

图片和扫描页面复用已配置模型服务及视觉模型选择，需要安装 `requirements.txt` 中的 Pillow、PyMuPDF 和办公文档依赖。单次消息附件提取限制与长期资料索引限制相互独立；处理失败或达到上限会在资料详情标明，可以重新处理。

用户不需要绑定家庭成员即可使用个人资料和记忆；共享给家庭前需要管理员完成既有的显式成员绑定。资料副本通过认证的 `/api/knowledge/documents/{id}/file` 下载，不要把 `HOME_DATA_DIR` 配置为静态目录。

删除和替换会删除资料库中对应的旧文件副本，历史元数据备份并不包含可恢复的文件副本。完整恢复应使用同一时点的整个 `knowledge/` 目录备份；恢复旧备份会恢复当时的共享范围与历史内容，恢复后需核对。删除不清除原上传文件、已有聊天或离线备份。

浏览器验收运行 `python scripts/validate_knowledge.py`，使用临时账号、临时存储和模型桩；真实模型验收分别运行 `python scripts/evaluate_knowledge.py` 与 `python scripts/evaluate_knowledge_chat.py`，使用合成材料并消耗当前模型服务额度。

## 009 家庭事项上线与回滚

当前家庭产品模式不主动发送通知。配置默认值为：

```dotenv
HOME_DATA_DIR=.data/home
HOME_TIMEZONE=Asia/Shanghai
HOME_REMINDER_DELIVERY_ENABLED=false
```

保留 `false`；新事项从不进入旧 `process_due_reminders()` 发送链。旧推送订阅和历史文件保留，工作台不展示通知权限、VAPID、发送测试或送达率。Web 工具集默认关闭通用 Shell；CLI 无成员身份时不会注册跨成员事项写工具。

升级步骤：

1. 先保留整个 `.data`、`files` 和 `.env`。更新代码和前端后确认服务没有启动旧发送任务。
2. 管理员在工作台展开“家庭成员绑定与迁移核对”，将旧数据涉及的有效账号逐一绑定为成员；不要把全部技术账号自动加入家庭。尚未绑定的账号无法查询事项。
3. 暂停服务写入，再预演迁移。默认使用 `.data/home`、`.data/users.json`；自定义路径必须同时传入 `--home-dir`、`--users`，自定义时区传 `--timezone`。

```bash
sudo systemctl stop claw-agent
.venv/bin/python scripts/migrate_family_tasks.py
.venv/bin/python scripts/migrate_family_tasks.py --apply
sudo systemctl start claw-agent
```

迁移前备份原家庭配置、提醒、周期、日志及账本，保存到 `HOME_DATA_DIR/backups/task-migration-<ID>`，报告含来源计数、稳定来源映射和待核对原因。每条记录按 `legacy_type:legacy_id` 去重，不按标题合并。旧 `sent/failed/snoozed/scheduled` 不表示事情完成；旧周期整条 `completed`、复杂规则、多收件人语义不明等保留为归档待核对，不自动恢复周期或推断历史。迁移完成前旧清单不会出现在新账本中。

上线后分别以交代者、负责人和第三名成员检查同一事项的可见性、完成/撤销和多人进度，再检查家庭未认领事项、每周完成及下期预览。管理员的待核对入口为工作台折叠面板或 `GET /api/home/tasks-migration/review`。

日常备份除部署脚本的整目录备份外，账本首次日内更新会在 `backups/<账本名>-YYYY-MM-DD.json` 保存更新前快照。不要单独备份提醒文件；`tasks.json` 中的操作去重、实例、来源映射和事件必须一起保存。账本损坏会返回 `ledger_corrupt`，不会以空账本覆盖损坏文件。

回滚先预演，核对所有切换后的新增/修改数据，再停服务执行：

```bash
.venv/bin/python scripts/migrate_family_tasks.py --rollback .data/home/backups/task-migration-实际备份ID
sudo systemctl stop claw-agent
.venv/bin/python scripts/migrate_family_tasks.py --rollback .data/home/backups/task-migration-实际备份ID --apply --writes-paused
```

执行回滚会先把当前完整账本导出为备份目录下 `post-cutover-<ID>.json`，再原子恢复迁移前账本。导出的新事项与修改需保留并人工核对合并，不能只恢复旧提醒文件后丢弃新指令。旧源文件始终保留且没有双写。确认数据处理完成后再启动目标版本。
