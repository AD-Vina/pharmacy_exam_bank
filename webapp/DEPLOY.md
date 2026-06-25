# 西药学副高级考试系统部署说明

## 本地运行

```powershell
cd pharmacy_exam_bank\webapp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

打开 `http://127.0.0.1:5000`。

## 一键本机运行

双击 `start_share.bat`。脚本会显示：

- 本机地址：`http://127.0.0.1:5000`

默认自动登录本机用户，不需要账号密码。默认只监听本机 `127.0.0.1`，手机和其他电脑不能访问，也不需要配置防火墙。

## 环境变量

- `SECRET_KEY`：生产环境必须设置为随机长字符串。
- `LOCAL_AUTO_LOGIN`：`1` 时自动登录本机用户，不需要账号密码；`0` 时恢复账号登录。
- `ALLOW_GUEST_LOGIN`：`1` 开启游客入口，`0` 关闭。
- `SECURITY_ENABLED`：`1` 开启限流、反爬和安全响应头。
- `SHARE_ACCESS_CODE`：可选访问码；留空则不需要访问码。
- `PORT`：本地默认 `5000`。

## 临时公网分享

Cloudflare Tunnel：

```powershell
cloudflared tunnel --url http://127.0.0.1:5000
```

ngrok：

```powershell
ngrok http 5000
```

启动后，把工具给出的 HTTPS 地址发给别人即可。电脑关机、程序停止或隧道断开后，链接会失效。

## Render 部署

1. 上传项目到 GitHub。
2. 在 Render 新建 Web Service，Root Directory 设为 `webapp`。
3. Build Command：`pip install -r requirements.txt`
4. Start Command：`gunicorn app:app`
5. 添加环境变量：`SECRET_KEY`、`LOCAL_AUTO_LOGIN`、`ALLOW_GUEST_LOGIN`、`SECURITY_ENABLED`。

免费实例可能休眠。SQLite 在部分平台不是永久存储，正式多人使用建议改 PostgreSQL 或挂持久盘。

## 健康检查

`/healthz` 返回：

```json
{"ok": true, "questions": 1660}
```

## 安全层

本机版默认包含自动登录、限流、常见爬虫 UA 拦截、禁止索引和安全响应头。

## 版权边界

公开仓库包含 1660 道公开版题库，不包含书本或指南扫描件，也不包含本地材料路径和大段原文摘录。需要使用本地完整题库时，可通过 `QUESTION_DATA_PATH` 单独指定。
