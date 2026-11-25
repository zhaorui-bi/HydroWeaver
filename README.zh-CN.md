<div align="center">
  <h1>HydroWeaver</h1>
</div>

从"看似合理"到"切实可行"：以智能体闭环优化驱动水处理工艺路线设计。

**Beta · v0.3.0-beta.1** | [English](./README.md) | **简体中文**

<p align="center">
  <a href="https://github.com/zhaorui-bi/HydroWeaver/actions/workflows/ci.yml"><img src="https://github.com/zhaorui-bi/HydroWeaver/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/zhaorui-bi/HydroWeaver/releases"><img src="https://img.shields.io/github/v/tag/zhaorui-bi/HydroWeaver?label=version&color=168dc4" alt="Version"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-239f83" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/Node.js-%E2%89%A524.15-18344c" alt="Node.js 24.15 或更高">
  <img src="https://img.shields.io/badge/Python-%E2%89%A53.10-2777b8" alt="Python 3.10 或更高">
</p>


## HydroWeaver 是什么？

HydroWeaver 是一个开源智能体框架，用于在水质、资源与成本约束下联合优化水处理工艺链配置与运行参数。其闭环智能体引擎协调以下四个核心模块：

* **知识驱动的配置生成**：17 类处理单元、12 类污染物、10 组专家先验模板
* **数值运行参数优化**：有界坐标搜索 + Hooke–Jeeves 模式外推
* **机理模拟与 LCOW 经济核算**：稳态质量守恒、渗透压、结垢/膜污染、CT/DBP 风险、CAPEX/OPEX/SEC 全生命周期成本
* **仿真反馈诊断与修订**：区分参数性失配（优化运行参数）与结构性缺陷（修订工艺拓扑）

HydroWeaver 可处理多类设计问题，包括：
* 砷污染地下水去除（预氧化 → 吸附 → 膜精处理）
* 铅与重金属控制（pH 调节 → 混凝 → 软化 → 过滤）
* 硝酸盐去除（生物反硝化 → 离子交换 → 消毒）
* 苦咸水与海水淡化（含浓盐水处置约束）
* 不同 NOM 负荷下的消毒副产物（DBP）风险最小化

HydroWeaver 完全基于 Python 标准库运行，**零外部仓库依赖**。可选地，配置 `HYDROWEAVER_SIM_PYTHON`（含 WaterTAP/IDAES/Pyomo/IPOPT）以启用严格流程模拟与 NLP 经济优化。

基准测试与方法对比，请参阅 [AquaDesignGym](#aquadesigngym)。


<div align="center">
<img src="./assets/screenshots/workbench.png" alt="HydroWeaver 工作台" width="900"/>
</div>


## 安装

需要 **Node.js ≥ 24.15**、**npm 12** 与 **Python ≥ 3.10**：

```bash
git clone https://github.com/zhaorui-bi/HydroWeaver.git
cd HydroWeaver
npm ci && npm run setup
```

验证内置引擎（无需外部仓库或额外数据下载）：

```bash
./bin/hydroweaver doctor --probe
./bin/hydroweaver tools --json
```

可选地配置模型提供商或 WaterTAP Python 解释器：

```bash
./bin/hydroweaver onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY --yes
```


## 快速开始

运行内置砷污染地下水合成案例：

```bash
./bin/hydroweaver optimize \
  --input examples/cases/arsenic-groundwater.json \
  --max-sim-calls 60 --wait
```

启动交互式界面：

```bash
./bin/hydroweaver       # 终端 TUI
./bin/hydroweaver chat  # 命令行 REPL
./bin/hydroweaver web   # 浏览器界面
npm start               # Electron 桌面端
```


## AquaDesignGym

AquaDesignGym 是一个交互式基准测试环境，将 12 个标准化设计任务与过程仿真神谕（Oracle）相结合，支持在相同模拟预算下对不同方法进行系统比较。

```bash
./bin/hydroweaver gym tasks                                      # 列出任务
./bin/hydroweaver gym eval --max-sim-calls 60 --seed 42 --wait  # 运行评测
```

评测协议覆盖三档进水扰动（`nominal`、`mild_shift`、`severe_shift`），报告 12 个基线与消融方法在可行设计率（FDR）、处理成本、鲁棒性与模拟效率方面的对比结果：

| 方法 | FDR（标准工况） | AUFBC | 模拟次数（中位数） |
| --- | --- | --- | --- |
| **HydroWeaver** | **1.00** | **0.7014** | **47** |
| HydroWeaver −诊断模块 | 0.83 | 0.5921 | 52 |
| HydroWeaver −历史记录 | 0.75 | 0.5312 | 60 |
| HydroWeaver −先验模板 | 0.67 | 0.4807 | 60 |
| CMA-ES（固定结构） | 0.58 | 0.3944 | 60 |
| 贝叶斯优化（BoTorch） | 0.50 | 0.3401 | 60 |
| 仅 Hooke–Jeeves | 0.42 | 0.2988 | 60 |
| 随机搜索 | 0.33 | 0.2211 | 60 |
| ReAct 智能体（GPT-4o） | 0.50 | 0.3390 | 58 |
| ReAct 智能体（Claude 3.5） | 0.42 | 0.2874 | 55 |
| 单次 LLM（GPT-4o） | 0.17 | 0.1102 | 1 |
| 基于规则的启发式 | 0.25 | 0.1680 | 12 |

*FDR = 可行设计率；AUFBC = 可行性-预算曲线下面积。所有方法共享相同模拟预算（`maxSimCalls=60`）与进水条件。*


## 闭环优化机制

智能体引擎通过迭代"设计–模拟–诊断–修订"循环运行：

```text
  知识驱动的配置生成
        │
        ▼
  数值运行参数优化
        │
        ▼
  机理模拟与 LCOW 经济核算
        │
        ▼
  仿真反馈违约诊断 ──► 约束全部满足？ ──► 记录并收敛
        │
        ├── 参数性失配 ──► refine_parameters
        └── 结构性缺陷 ──► revise_structure
```

#### 诊断逻辑

`参数性失配`：约束违反归因于运行参数（压力不足、药剂量不够、通量过高）—— 路由至 `refine_parameters` 进行坐标/Hooke–Jeeves 调整。

`结构性缺陷`：违反无法仅靠参数调整解决（缺少必要处理能力、单元序列不兼容、未覆盖污染物）—— 路由至 `revise_structure` 进行工艺拓扑修改。


## 端到端测试

运行完整检查套件（71 个 Vitest 单元测试、24 个 Python 测试、188 个 TUI 测试）：

```bash
npm run check
```

仅执行运行时审计：

```bash
npm run audit:runtime
```


## 贡献者

HydroWeaver 由姜肇睿开发，并得到 HydroWeaver 社区贡献者的持续支持。

## 引用

如果本项目对您的研究有所帮助，请引用：

```bibtex
@software{hydroweaver2026,
  title     = {HydroWeaver: From Plausible to Feasible Water Treatment Train Designs
               through Agentic Closed-Loop Optimization},
  author    = {Jiang, Zhaorui and {HydroWeaver contributors}},
  year      = {2026},
  version   = {0.3.0-beta.1},
  license   = {MIT},
  url       = {https://github.com/zhaorui-bi/HydroWeaver}
}
```

完整引用元数据见 [CITATION.cff](./CITATION.cff)。发表结果时请注明 HydroWeaver 版本号、模拟器模式、优化预算与模型配置。

## 许可

MIT 许可 — 详见 [LICENSE](./LICENSE) 与 [licenses/THIRD_PARTY_NOTICES.md](./licenses/THIRD_PARTY_NOTICES.md)。
