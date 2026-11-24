[English](../TROUBLESHOOTING.md) | **简体中文**

# 故障排查

先执行诊断：

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

## 安装与构建

- 若提示 Node 版本低于 24.15，请升级后执行 `npm ci && npm run setup`。
- 若提示缺少构建产物或 Web 资源，请在根目录重新执行 `npm run setup`。

## 内置引擎与 WaterTAP 后端

- **未检测到 Python 或需指定版本**：设置 `HYDROWEAVER_PYTHON=/path/to/python3` 或运行 `./bin/hydroweaver onboard --hydroweaver-python /path/to/python3 --yes`。
- **WaterTAP 工具提示未配置**：设置 `export HYDROWEAVER_SIM_PYTHON=/path/to/watertap-env/bin/python` 并再次探测 `doctor --probe`。
- **索引缺失**：执行 `hydroweaver_build_indexes` 重建 `HYDROWEAVER_HOME` 下的本地混合检索索引。

## 闭环优化与约束

- **污染物在归一化后缺失**：先用 `hydroweaver_catalog` 查询标准名或已知同义词。
- **优化以 `stalled` 或 `budget_exhausted` 结束**：查看最终轮 `unresolved` 违约类别及 `routing_decision`，可适当增大 `--max-sim-calls` 或核对原水与场地约束是否存在根本物理冲突（例如不允许浓水处置却要求无浓缩预处理的高回收膜分离）。

## 隐私与问题反馈

`~/.hydroweaver`、`hydroweaver-data/` 及工作区任务目录含配置与输入，分享日志前请先脱敏。
