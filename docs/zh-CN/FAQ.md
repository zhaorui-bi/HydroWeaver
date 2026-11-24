# 常见问题

[English](../FAQ.md) | **简体中文**

### HydroWeaver 是什么？

HydroWeaver 是面向水处理工艺路线设计的独立智能体闭环优化框架，可在水质、资源与成本约束下联合优化工艺单元组合与连续运行参数，并内置交互式基准环境 **AquaDesignGym** 与可选 **WaterTAP** 流程模拟接口。

### 是否依赖外部仓库或第三方 Python 包？

不依赖。默认模式通过内置 `hydroweaver_py` 与 `aquadesigngym` 在 Python 3.10+ 标准库上直接运行，零外部仓库依赖、零额外 pip 安装要求。

### 闭环联合优化解决了什么问题？

传统一次生成方案只“看似合理”，但缺乏质量守恒、渗透压、结垢、膜污染、消毒 CT 与全生命周期成本（LCOW）验证。HydroWeaver 将知识驱动配置生成、有界坐标+Hooke–Jeeves 数值优化、稳态机理与 LCOW 模拟、违约诊断与结构/参数路由以及 `SharedDesignHistory` 集成在同一闭环中。

### AquaDesignGym 评测协议包含哪些维度？

在严格匹配的 `max_sim_calls` 模拟预算下，在 12 个标准化设计任务与 3 种进水扰动（`nominal`、`mild_shift`、`severe_shift`）上，对比 HydroWeaver 与常规优化器、既有智能体基线及 5 类组件消融，汇报可行设计率（FDR）、平均可行 LCOW、SEC、达到可行所需模拟次数（S2F）与可行率–预算曲线下面积（AUFBC）。

### 何时使用 `HYDROWEAVER_SIM_PYTHON`？

当需要运行严格的 WaterTAP / IDAES / Pyomo / IPOPT NaCl 流程图仿真与 NLP 经济优化（`optimizeDesign: true`）时，将该环境变量指向 WaterTAP 环境即可。详见 [SIMULATION.md](../SIMULATION.md)。

### 推荐方案能否直接用于工程施工？

不能。模型仿真与 AquaDesignGym 的“feasible”仅针对所建数学约束成立，正式工程实施前仍须完成专业审校、烧杯/中试试验与场地合规设计。

### 如何报告问题？

请在 <https://github.com/zhaorui-bi/HydroWeaver/issues> 提交脱敏后的 `hydroweaver doctor --json`、系统环境版本与最小复现案例；安全漏洞请参阅 [SECURITY.md](../../SECURITY.md)。
