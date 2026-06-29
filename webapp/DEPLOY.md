# 西药学副高级考试系统本地运行说明

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

双击 `start_local.bat`。脚本会显示：

- 本机地址：`http://127.0.0.1:5000`

默认自动登录本机用户，不需要账号密码。默认只监听本机 `127.0.0.1`，其他设备不能访问，也不需要配置防火墙。

## 环境变量

- `SECRET_KEY`：生产环境必须设置为随机长字符串。
- `LOCAL_AUTO_LOGIN`：`1` 时自动登录本机用户，不需要账号密码；`0` 时恢复账号登录。
- `SECURITY_ENABLED`：本地一键运行默认关闭；需要自行开启时设为 `1`。
- `PORT`：本地默认 `5000`。

## 健康检查

`/healthz` 返回：

```json
{"ok": true, "questions": 1760}
```

## 使用范围

本项目按本机使用设计，默认只监听 `127.0.0.1`，这里只保留本机运行说明。

## 版权边界

公开仓库包含 1760 道公开版题库：医院药学 1062 题、临床药学 100 题、指南/共识 598 题。不包含书本或指南扫描件，也不包含本地材料路径和大段原文摘录。需要使用本地完整题库时，可通过 `QUESTION_DATA_PATH` 单独指定。
