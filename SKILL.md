---
name: development-reference-library
description: "需要为开发问题查找可靠资料或已核实能力时使用：AI 按具体任务检索官方文档、Skill、MCP、API 与工具入口，只向用户呈现 1–5 条相关结果、调用方式、配置条件与核实状态。用于查框架文档、找官方能力、确认服务如何接入、比对工具入口；不替代项目源码阅读。不用于不依赖外部资料的小改、视觉设计参考或完整开发规划；这些分别走原项目、design-reference-library 或 wf-vibecode。"
license: MIT
metadata:
  version: "0.1.0"
  updated_at: "2026-11-25"
---

# Development Reference Library

这是 AI 的按需检索工具，不是交给用户浏览的链接目录。

用户只应看到与当前问题最相关的 1–5 条结果、选择理由、调用方式、配置条件和核实状态。不要转交整份 `catalog.json`、全部分类或完整命中列表。

## 先看哪里

1. 项目已有实现与项目内文档。
2. 官方文档、官方仓库与官方示例。
3. 本库登记的官方能力或服务入口。
4. 权威聚合入口与成熟社区工具。
5. 普通网页检索。
6. 确实没有可用能力时，才讨论新实现。

本库只负责第 3 步的索引；它不能代替第 1、2 步。

## 检索

保留用户原话作为一个具体问题，再运行：

```bash
py -3 <skill-root>/scripts/references.py search "Supabase 数据库权限" --limit 3
py -3 <skill-root>/scripts/references.py search "Next.js 部署" --json --limit 2
py -3 <skill-root>/scripts/references.py search "网页浏览器测试" --category 测试安全 --kind mcp
```

- `--category` 接受分类 id 或中文名，可重复或用逗号分隔。
- `--kind` 接受 `documentation`、`skill`、`skill+mcp`、`mcp`、`api`、`service`、`directory`、`toolkit`。
- `--limit` 只能是 1–5，默认 3。
- 命中 0 条时脚本明确说明没有匹配，不编造条目；换用任务名、英文名或分类再查。

检索考虑名称、别名、任务描述和分类；中文连续输入会拆成双字片段匹配，所以“数据库权限”“网页浏览器测试”这类不带空格的问法也能命中。

## 四种对象

| 对象 | 本库里的 kind | 可以怎样用 | 不能怎样说 |
| --- | --- | --- | --- |
| 资料 | `documentation` | 阅读、引用、核实 | 不能说已安装、已调用 |
| 能力 | `skill`、`mcp`、`skill+mcp`、`toolkit`、`directory` | 按条目说明配置后调用 | 未实测不能说可用 |
| 服务 | `service`、平台型条目 | 用户明确选择后配置 | 不能默认建资源或产生费用 |
| 工具 | `api`、检索脚本 | 维护索引与证据 | 不能用自写脚本冒充官方能力 |

## 状态

- `verified`：官方入口已核实；**不代表已登录，也不代表调用过云资源**。
- `needs_setup`：入口存在，但需要账号、密钥、项目或安装步骤。
- `reference_only`：只读资料，不承诺任何程序化接入。
- `caution`：入口可用性、许可或行为存在已知疑问。
- `unavailable`：当前不可用。

回答时必须把“官方入口存在”“已配置”“已成功调用”分成三件事。未配置的服务，只说需要什么条件，不说已经接通。

## 从结果到回答

1. 用用户场景从命中里选 1–2 条，最多 5 条；不机械罗列全部条目。
2. 打开官方链接核实与当前问题相关的部分；以项目源码和官方文档为准。
3. 回答“能解决什么、怎么调用、需要什么配置、核实到哪一天”。
4. 费用、许可或配额未知时写 unknown，不猜数字。
5. 条目只是入口索引；具体 API 用法仍以该来源当日文档为准。

## 使用边界

- 不安装技能、不登录、不调用需要密钥或会产生费用的服务；这些由用户明确决定后另行执行。
- 不把条目状态当作项目结论；版本差异、许可与配额必须回到官方页面确认。
- 不改用户项目、工作流、全局配置或凭据；本 Skill 只读写自己的目录。
- 检索结果为 0 时直说没有可靠条目，不用相似名词凑数。

## 维护

```bash
py -3 <skill-root>/scripts/references.py check
py -3 -m unittest discover -s tests -p "test_*.py" -v
```

`check` 校验必填字段、重复 ID、分类、URL、状态、日期、证据与疑似密钥；测试全部离线运行。

条目数量不是目标；首批示例会随真实使用扩充或淘汰。`mcp+cli` 可作为后续类型扩展，目前微信文档与 CLI 仍按 `documentation` 登记，避免把非 MCP 入口误标为已接入协议。

新增条目时在 `catalog.json` 的 `entries` 里补齐字段，并遵守：

- `status` 只按实际核实程度填写；
- `last_verified` 写真实核对日期，`evidence` 至少一条带 URL 且带该日期；
- 费用、许可未知就写 `unknown`；
- 不写密钥、cookie、token、批量安装命令，也不放爬虫。

目录结构：`SKILL.md`、`catalog.json`、`scripts/references.py`、`tests/test_references.py`、`README.md`。
