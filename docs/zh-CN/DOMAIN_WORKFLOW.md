# 面向水处理研究的 HydroWeaver 工作流与评测协议

[English](../SCIENTIFIC_WORKFLOWS.md) | **简体中文**

HydroWeaver 将水处理工艺合成建模为**离散工艺链拓扑与连续运行参数的闭环联合优化**问题，并结合 **AquaDesignGym** 实现可复现的受限预算对比评测。

## 1. 闭环工作阶段

1. **运行准备与目录核对**：通过 `hydroweaver_status` 和 `hydroweaver_catalog` 校验 17 类单元与 12 类污染物的受控名称及参数边界。
2. **案例完备性与语义保留（`hydroweaver_assess_case`）**：严格保留硝酸盐基准（`as NO3` vs `as N`）、硬度基准（`as CaCO3`）、砷价态（`As(III)` / `As(V)`）、设计流量与场地资源边界。
3. **证据检索（`hydroweaver_retrieve_evidence`）**：从内置单元/模板先验库及 `HYDROWEAVER_HOME/ingest` 暂存记录中检索相关条目。
4. **闭环联合优化（`hydroweaver_optimize_trains`）**：结合先验生成、有界坐标+Hooke–Jeeves 数值优化、稳态机理与 LCOW 模拟、违约诊断（决定 `refine_parameters` 或 `revise_structure`）及 `SharedDesignHistory` 去重记录。
5. **可选 WaterTAP NLP 验证（`hydroweaver_simulate_train`）**：在配置 `HYDROWEAVER_SIM_PYTHON` 时使用 IPOPT 验证流程图或直接最小化 LCOW。
6. **审计与溯源（`hydroweaver_audit_report`、`hydroweaver_job_manifest`）**：核查证据声明、约束状态与 SHA-256 输入输出指纹。

## 2. AquaDesignGym 基准测试

`hydroweaver gym tasks` 与 `hydroweaver gym eval`（对应 MCP 工具 `hydroweaver_gym_tasks` 和 `hydroweaver_evaluate_gym`）覆盖：

- **12 个标准任务（`ADG-01` 至 `ADG-12`）**：含农村含砷地下水、硝酸盐无浓水、高结垢半咸水反渗透、高污染地表水、PFAS 痕量控制、海水淡化能耗受限、DBP 控制及复合污染体系。
- **9 类许可动作**：`set_chain`、`add_unit`、`remove_unit`、`replace_unit`、`reorder_chain`、`set_parameters`、`refine_parameters`、`step_simulate`、`stop`。
- **匹配预算对比与组件消融**：在相同 `max_sim_calls` 下对比 HydroWeaver、常规优化器（`EvolutionaryMINLP`、`TemplateGridSearch`、`RandomSearch`）、基线智能体（`OneShotKnowledge`、`RuleCriticLoop`、`ReActBlindAgent`）及 5 项消融（`HW-NoParamOpt`、`HW-NoStructRev`、`HW-NoDiagRouter`、`HW-NoKnowledge`、`HW-NoHistory`）。
- **进水扰动鲁棒性**：检验在 `nominal`、`mild_shift` 与 `severe_shift` 三类工况下的零样本可行保持率。

## 3. 示例案例

- [含砷地下水案例](../../examples/cases/arsenic-groundwater.json)
- [WaterTAP 模拟说明](../SIMULATION.md)
