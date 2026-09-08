# calc 库除法修复

Slug: calc-fix
Created: 2026-09-05
Status: 进行中

## 目标
让 calc.py 的 divide 对非整除输入返回正确的浮点结果，测试全绿。

## 完成标准
- [ ] `.venv/bin/pytest tests/ -q` 0 failed
- [ ] divide(7, 2) == 3.5

## 不做
- 不改 add 的行为
- 不引入第三方依赖

## 约束
- 保持 divide(a, 0) 抛 ZeroDivisionError
- 用户要求用中文汇报

## 验证方法
`.venv/bin/pytest tests/ -q`

## 起点
2026-09-05：`.venv/bin/pytest tests/ -q` 4 个测试 1 failed（test_divide_fraction）

## 协作约定
- 改动前先跑测试
- 用中文汇报

## Open questions
- 是否需要支持 Decimal 输入？（用户未答）
