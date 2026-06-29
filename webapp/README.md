# Web App

这是题库系统的 Flask Web 应用。

## 启动

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY="local-dev-secret"
python app.py
```

打开 `http://127.0.0.1:5000`。

## 题库数据

应用会按顺序加载：

1. `QUESTION_DATA_PATH`
2. `data/questions_public.json`
3. `data/sample_questions.json`

公开仓库默认包含 1815 道公开版题库：医院药学 1062 题、临床药学 155 题、指南/共识 598 题。该文件保留题干、选项、答案、解析、考点、分类和来源分组信息，不包含扫描件、本地材料路径和大段原文摘录。

## 本机运行

双击 `start_local.bat` 可以在本机启动服务。默认自动登录本机用户，不需要账号密码；默认只监听 `127.0.0.1`，其他设备不能访问。

更多本地运行说明见 `DEPLOY.md`。
