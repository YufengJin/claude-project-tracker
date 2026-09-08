## 2026-09-05 · session 1
Goal:     建立项目档案并复现问题
Did:      建立项目档案；跑测试复现
Result:   部分。`.venv/bin/pytest tests/ -q` 4 passed 中 1 failed（test_divide_fraction: assert 3 == 3.5）
Learned:  失败只在非整除输入上出现
Commits:  无
Next:     定位 divide 实现
Open:     是否需要支持 Decimal 输入

## 2026-09-06 · session 2
Goal:     定位原因
Did:      读 calc.py，确认 divide 用了 `//`
Result:   成功。`python -c "from calc import divide; print(divide(7,2))"` 输出 3
Learned:  不是测试问题，是实现用了整除；用户否决改测试期望
Commits:  无
Next:     把 `//` 改成 `/`，跑全量测试
Open:     无
