---
title: {{NAME}}
parent:
status: active
---
<!-- 研究树根节点（问题）。一节点一文件，文件名就是 ID：Q<n> 问题、H<n> 假设，全局递增（pt tree <slug> --next Q|H 给下一个号）。
     子节点写 parent: <父 ID>；status: open | active | parked | closed；closed 时加 verdict: supported | refuted | inconclusive | superseded，superseded 再加 by: <新 ID>。
     尖括号注释不进简报和 tree.html，写完可删。 -->

## 判别
<!-- 为什么问、什么算答完。假设节点写：预测 / 什么结果说明它错 / 对立解释 / 预算。事后补写的标「事后整理」。 -->

## 结论
<!-- closed 时必填：判断 + 怎么知道的 + 引用实验 id 与证据路径。读数不抄，只在 experiments.md。更正就地改，注明原因。 -->

## 当前认识
<!-- 项目级，整个项目只这一份：现在相信什么、依据哪几行实验。 -->

## 约束
<!-- 每份 --ctx 都会带：协议、切分与暴露、禁读的数据或文件。 -->

## 教训
<!-- 人工提炼的「别再这样做」，每条写适用条件与出处（实验 id / 节点 ID）。 -->
