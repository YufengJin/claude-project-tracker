# 计划
Updated: 2026-09-06 (session 2)

## 策略
先复现失败，再最小改动修 divide，最后跑全量测试。

## 步骤
- [x] 1. 复现 test_divide_fraction 失败
- [x] 2. 定位原因
- [ ] 3. 修改 divide 实现 ← 进行中
- [ ] 4. 全量测试并 checkpoint

## 风险
- 改成 `/` 后 divide(6, 3) 返回 2.0，若有地方依赖 int 类型会炸（目前测试用 == 比较，2.0 == 2 通过）
