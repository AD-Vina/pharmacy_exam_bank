# Pharmacy Exam Bank

一个基于 Flask 的本地题库练习与模拟考试系统，在自己的电脑上运行和做题。

## 功能

- 题库浏览、筛选、搜索
- 按医院药学、临床药学、指南/共识筛选
- 随机练习、专项练习、模拟考试
- 单选题、多选题、案例题、配伍题评分
- 答案解析、考点、来源展示
- 错题本、收藏、历史记录
- 本机自动进入，无需账号密码

## 题库数据

本仓库包含公开版题库：`webapp/data/questions_public.json`，共 1965 题。

当前分组：

- 医院药学：1062 题
- 临床药学：305 题
- 指南/共识：598 题

不包含以下内容：

- 教材或指南的 PDF、扫描图片、Word/PPT 等原始文件
- 数据库、日志、虚拟环境、本地生成材料
- 本地电脑上的材料路径
- 大段原文摘录字段，例如 `source_quote`
- 解析中附带的长段教材/指南原文

公开版题库保留题干、选项、答案、解析、考点、分类和来源分组信息，可以直接运行做题。

数据加载顺序：

1. `QUESTION_DATA_PATH` 指定的 JSON 文件
2. `webapp/data/questions_public.json`
3. `webapp/data/sample_questions.json`

如需在自己电脑上使用未删来源摘录的本地题库，把 `QUESTION_DATA_PATH` 设置为那个 JSON 文件路径即可。

## 本地运行

```powershell
cd webapp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY="local-dev-secret"
python app.py
```

打开 `http://127.0.0.1:5000`。

本机使用也可以直接双击 `webapp/start_local.bat`，启动后打开 `http://127.0.0.1:5000`。默认不需要账号密码，只在本机访问。

## 环境变量

详见 `webapp/.env.example`。

## 开源协议

代码使用 MIT License。题库内容、教材摘录、指南材料不包含在本开源协议内。
