# 怎么写：字段规则与正反例

模板在 [templates/](templates/)，`pt.sh new` 会自动实例化。字段名固定，不改名、不省略，空的写 `无`。日期一律 `YYYY-MM-DD`。

## 判据

一条内容值不值得写：**一个月后、在另一个话题的会话里，这条还有用吗？**
目标、决策、约束、死路、用户原话：有用。"改了 3 个 typo"、"重构了一下"：没用，看 commit。

用户说的和你推断的分开。推测要标"（推测）"。用户答不上的写"待定"，**不要替用户猜然后写成事实**，后续会话会把它当用户原话执行。

## journal 条目

```
## YYYY-MM-DD · session N · @hostname
Goal:     这次打算做什么
Did:      实际做了什么
Result:   成功 / 失败 / 部分。必须带证据
Learned:  之前不知道、现在知道的。失败的路写这里，并同步到 state 的"别再试"
Commits:  相关 commit 短哈希或分支，无则写 无
Next:     下一步，具体到能直接动手
Open:     新冒出来的问题
```

- `Result` 反例："完成了"。正例："完成。`pytest tests/ -q` 从 12 failed 降到 0 failed，41s"。
- `Learned` 反例："学到很多"。正例："Tsit5 对这个 ODE 太刚性会发散，换 Kvaerno5 后收敛"。
- session N = `grep -c '^## ' journal.md` + 1，brief 会直接打印（连同本机 hostname）。标题里的 `@hostname` 让多机时知道这条是在哪台机器上写的。**一次会话只有一条**：同一会话内再次 checkpoint 只改写本会话这条末尾条目，历史条目一个字节都不动。

## state.md

- 「一句话概括」的第一行就是 INDEX 里的一句话，`pt index` 会改写它；后面几行随意补充。
- 硬上限 100 行。超了就把"已完成"整段挪进 `archive/state-YYYY-MM-DD.md`（顶部加一行 `Archived from state.md on YYYY-MM-DD`），这里留一行摘要。
- "别再试"是最值钱的一节：走不通的路 + 为什么。每次 checkpoint 从 journal 的 `Learned` 提升过来。
- "快速启动"要能直接复制运行。

## plan.md

写"打算怎么做"，与 state 的"现在在哪"分开。已完成步骤保留打勾。重大方向调整先在 journal 记一条为什么，再重写。

## decisions.md

只追加，编号递增。推翻旧决定：新增一条 ADR，把旧条目 `Status` 改为 `已推翻（见 ADR-00NN）`，这是对已有条目唯一允许的修改。

## charter.md

- `Workdir`：一个或多个绝对路径，空格分隔。SessionStart hook 只在当前目录落在其中之一时才加载这个项目。项目跨仓库就写多个。
- `Host`：代码和硬件所在机器的 hostname，`Workdir` 按那台机器解释。立项时自动填本机；代码在别处用 `pt new --host`。`待定位` 表示迁移时判断不出来，要手工改。
- `Status`：`进行中` `暂停` `已完成` `已放弃`。用 `pt.sh index <slug> "<一句话>" <状态>` 改，会同步 INDEX。
- 完成标准打勾的唯一依据是 journal 里有对应证据条目。

## INDEX.md

```
| Slug | 名称 | 状态 | 主机 | 最后更新 | 一句话 |
```

生成视图，不手编：名称取 charter 标题，状态取 `Status`，主机取 `Host`，日期取最后一次提交，一句话取 state「一句话概括」首行。`pt new` / `pt index` / `pt list` / 同步都会重建它。
