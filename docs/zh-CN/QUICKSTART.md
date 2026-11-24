[English](../QUICKSTART.md) | **简体中文**

# 快速上手

## 1. 环境要求

- **Node.js ≥ 24.15.0** 与 **npm 12**
- **Python ≥ 3.10**（默认科学引擎与 AquaDesignGym 仅需标准库）
- 可选：独立 WaterTAP / IDAES / Pyomo / IPOPT 环境（用于 `hydroweaver_simulate_train`）

## 2. 安装与构建

```bash
git clone https://github.com/zhaorui-bi/HydroWeaver.git
cd HydroWeaver
npm ci
npm run setup
```

## 3. 验证内置引擎

无需任何外部仓库或额外下载：

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

如需显式固定 Python 解释器：

```bash
./bin/hydroweaver onboard --hydroweaver-python /path/to/python3 --yes
```

## 4. 配置对话模型提供方（仅 CLI/TUI/Web 对话需要）

```bash
export DEEPSEEK_API_KEY="YOUR_KEY"
./bin/hydroweaver onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY --yes
```

离线闭环优化与 AquaDesignGym 评测无需任何对话模型 API 密钥。

## 5. 运行闭环联合优化与 AquaDesignGym

```bash
# 结构与运行参数闭环联合优化
./bin/hydroweaver optimize \
  --input examples/cases/arsenic-groundwater.json \
  --top-k 3 \
  --max-rounds 4 \
  --max-sim-calls 60 \
  --wait

# 查看 AquaDesignGym 任务、动作、扰动与对比方法
./bin/hydroweaver gym tasks

# 按匹配模拟预算评测所有方法与消融组件
./bin/hydroweaver gym eval --max-sim-calls 60 --seed 42 --wait
```

## 6. 启动交互式工作台

```bash
./bin/hydroweaver       # 完整终端 TUI
./bin/hydroweaver chat  # 命令行 REPL
./bin/hydroweaver web   # 本地 Web 界面
npm start               # Electron 桌面端
```

Windows 用户请将 `./bin/hydroweaver` 替换为 `npm run cli --`。
