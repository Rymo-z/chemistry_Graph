# RAGAS 评估报告

- 样本数：14
- judge LLM：deepseek-v4-flash
- embedding：D:\Model_Pro_Train\中医知识图谱\06-安装包及模型\bge-large-zh-v1.5

## 总体指标（均值）

| 指标 | 得分 | 含义 |
|------|------|------|
| faithfulness | **0.7976** | 答案是否忠实于检索上下文（越低越可能幻觉） |
| context_precision | **0.6429** | 检索上下文是否相关且排位靠前 |
| context_recall | **0.6429** | 真值信息是否被检索上下文覆盖 |
| answer_relevancy | **0.5632** | 答案与问题的相关度 |

## 逐条明细

| 样本 | 问题 | 向量命中 | 图谱命中 | faithfulness | context_precision | context_recall | answer_relevancy |
|------|------|:---:|:---:|:---:|:---:|:---:|:---:|
| chem_methanol_cas | 甲醇的CAS号是多少？它还有哪些别名？ | 5 | 0 | 0.75 | 1.0 | 1.0 | 0.481 |
| chem_ethanol_cas | 无水乙醇的CAS号是多少？ | 5 | 0 | 0.75 | 1.0 | 1.0 | 0.905 |
| chem_potassium_cyanide | 氰化钾的别名是什么？CAS号是多少？ | 5 | 0 | 1.0 | 1.0 | 1.0 | 0.929 |
| chem_hydrogen_sulfide | 硫化氢的CAS号是多少？ | 5 | 0 | 0.25 | 1.0 | 1.0 | 0.525 |
| chem_ammonia | 氨有哪些别名？ | 5 | 0 | 1.0 | 1.0 | 1.0 | 0.787 |
| chem_benzene | 苯的CAS号是多少？它有什么别名？ | 5 | 0 | 1.0 | 0.0 | 0.0 | 0.918 |
| reg_hazardous_chem_regs | 《危险化学品安全管理条例》是什么时候施行的？文号是什么？ | 5 | 0 | 0.667 | 1.0 | 1.0 | 0.888 |
| reg_accident_regs | 《生产安全事故报告和调查处理条例》是哪一年施行的？ | 5 | 0 | 1.0 | 1.0 | 1.0 | 0.817 |
| reg_safety_law | 《中华人民共和国安全生产法》2021年修正版是什么时候施… | 5 | 0 | 1.0 | 1.0 | 1.0 | 0.827 |
| reg_fire_law | 《中华人民共和国消防法》是哪一年修正的？什么时候施行？ | 5 | 0 | 1.0 | 1.0 | 1.0 | 0.808 |
| wp_hot_work_levels | 动火作业分为哪几个级别？ | 5 | 0 | 0.778 | 0.0 | 0.0 | 0.0 |
| wp_hot_work_validity | 二级动火安全作业票的有效期是多长？ | 5 | 0 | 0.8 | 0.0 | 0.0 | 0.0 |
| wp_confined_space_validity | 受限空间安全作业票的有效期是多少？ | 5 | 0 | 0.6 | 0.0 | 0.0 | 0.0 |
| wp_gas_test_interval | 动火前气体分析取样时间与动火开始时间间隔有什么要求？ | 5 | 0 | 0.571 | 0.0 | 0.0 | 0.0 |