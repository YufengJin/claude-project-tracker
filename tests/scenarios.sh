# scenario name -> prompt
declare -A PROMPT
PROMPT[list]='有哪些项目？'
PROMPT[resume]='继续 calc-fix，我们做到哪了？先汇报，这一轮不要改代码。'
PROMPT[checkpoint]='继续 calc-fix：完成下一步（修 divide 并跑测试），做完后 checkpoint。'
PROMPT[new]='立一个项目：给 calc 加 power(a, n) 函数。做完的样子：.venv/bin/pytest tests/ -q 全绿，且 power(2, 10) == 1024。不做：不支持负指数、不支持浮点指数。约束：不改现有 add/divide 的行为。验证：.venv/bin/pytest tests/ -q。这一轮只建档案，不写代码。'
SCENARIOS="list resume checkpoint new"
