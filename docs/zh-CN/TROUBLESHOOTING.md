[English](../TROUBLESHOOTING.md) | 简体中文

# 故障排查

先运行：

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

Windows 用户请用 `npm run cli --` 代替 `./bin/hydroweaver`。

## HydroWeaver 安装

### Node 版本低于 24.15

升级 Node，重新打开终端，然后执行 `npm ci && npm run setup`。

### CLI 提示引擎未构建

在仓库根目录运行 `npm run setup`。启动器需要
`engine/apps/hydroweaver/dist/cli.mjs`。

## 后端发现

### 找不到 `hydroweaver_backend`

```bash
./bin/hydroweaver onboard --hydroweaver-repo /absolute/path/to/OpenAqua
# 或
export HYDROWEAVER_REPO=/absolute/path/to/OpenAqua
```

有效仓库应包含 `water_treatment_agent/requirements.txt`、
`water_treatment_agent/app/workflows/pipeline.py`、`test_openaqua.py` 和
`test_retrieval.py`。

### 选择了错误的 Python

```bash
export HYDROWEAVER_PYTHON=/path/to/OpenAqua/water_treatment_agent/.venv/bin/python
./bin/hydroweaver doctor --probe
```

Windows 请指向 `.venv\Scripts\python.exe`。

### 缺少 `openai`、`rank_bm25` 等依赖

```bash
cd /path/to/OpenAqua/water_treatment_agent
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 数据与索引

### 状态显示 `taxonomy_available: false`

OpenAqua 数据位于 Hugging Face：

```bash
cd /path/to/OpenAqua/water_treatment_agent
python -m pip install -U huggingface_hub
hf download zhaorui-bi/OpenAqua data.zip WContBench/ \
  --repo-type dataset \
  --revision cc2d3c620e8ada7c62fa922cf3a827d8b42889e3 \
  --local-dir ../hf_openaqua
unzip ../hf_openaqua/data.zip -d .
```

压缩包已经包含 `data/`；若使用 `-d data`，会错误地产生 `data/data/`。

确认 `data/unit-level/taxonomy.json` 存在。

### 索引缺失或 chunk 数为 0

确认 TDB/案例数据解压到了 `water_treatment_agent/data/`，然后调用
`hydroweaver_build_indexes`。应生成：

```text
data/processed/indexes/corpus.jsonl
data/processed/indexes/bm25_index.pkl
```

### 检索没有证据

依次检查：查询是否归一化出标准污染物、数据路径是否正确、索引是否非空、污染物名称是否存在于分类体系，以及日志是否有索引或模式错误。

## 模型

### HydroWeaver 提示未配置模型

运行 `./bin/hydroweaver onboard`，或在 TUI 中使用 `/provider`。HydroWeaver 提供方凭据与 OpenAqua 的 `OPENROUTER_API_KEY` 相互独立。

### OpenAqua 无法从自然语言抽取字段

未设置 `OPENROUTER_API_KEY` 时，OpenAqua 会使用回退模式，不保证解析自由文本中的所有信息。请提供结构化字段，或在启动 HydroWeaver/Web/桌面端的环境中设置该变量。

### 桌面端看不到环境变量

从 Finder/开始菜单启动的 GUI 可能继承不同环境。可从已导出变量的终端启动，或使用系统级安全配置；修改后重启应用。

## 查询与约束

### 污染物在归一化后消失

说明该名称未被分类体系识别。先使用 `hydroweaver_catalog` 搜索标准名称或已知同义词，不要自行伪造 ID。

### 所有候选工艺链都被拒绝

检查具体规则。常见原因包括未知处理单元、饮用水缺少消毒、无浓水处置条件却使用膜分离、或能耗约束冲突。自动修订能力有限，必须人工审核。

## 任务

### 长任务似乎丢失

按顺序调用 `hydroweaver_job_list`、`hydroweaver_job_status`、
`hydroweaver_job_manifest`，再读取有界日志尾部或 `errors` 视图。

新任务默认保存在 `<HYDROWEAVER_WORKDIR>/hydroweaver-jobs`；未设置工作区时使用
`<当前目录>/hydroweaver-jobs`。命令行和 MCP 也会查找各自当前目录中的旧版 MCP
任务，并在原位置继续使用。其他历史启动目录无法自动发现：将
`HYDROWEAVER_JOBS_DIR` 显式设为对应的 `hydroweaver-jobs` 目录即可访问。显式设置后
只使用该目录；如果两个默认目录存在相同 ID，也需要显式选择目录，不要移动或
覆盖任务记录。

### 任务成功但没有产物列表

`hydroweaver_job_artifacts` 只检查显式 `--output` 路径。查看任务状态中的
`configuredOutput`，并从有界日志中确认后端实际写入位置。

## Web 与桌面端

### Web 页面打不开

复制 `hydroweaver web` 输出的完整 `Local:` 地址（包含令牌）；可尝试
`--port 8765`，并检查代理/防火墙是否拦截回环地址。

### 桌面端启动超时

从终端运行 `npm start` 保留日志，在菜单中选择“文件 → 重启引擎”。必要时重新执行 `npm run setup`；调试模式为 `HYDROWEAVER_DEBUG=1 npm start`。

## 隐私

`~/.hydroweaver`、`hydroweaver-data/` 和工作区任务目录可能包含提示词、水质数据、路径、模型输出和凭据。公开分享前必须脱敏。

## 仍未解决

在 <https://github.com/zhaorui-bi/HydroWeaver/issues> 提交：脱敏后的
`hydroweaver doctor --json`、操作系统、Node/npm/Python 版本、OpenAqua commit、
`hydroweaver_status` 输出、最小复现输入和有界错误日志。
