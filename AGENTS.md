<!-- vnstock-guide:start -->
## vnstock

This project uses the Python library `vnstock` generation 6 (preview, with `vnstock-oapi`).

- Environment: `~/.venv_6x` (Windows `$HOME\.venv_6x`) unless noted here. Run code and commands with `~/.venv_6x/bin/python` and `~/.venv_6x/bin/vnstock`. Do not install vnstock into another Python.
- At the start of a session: run `vnstock onboard` and follow it; `vnstock doctor` when something fails.
- Every data call names a source: `Market("<nguồn>").equity("FPT").ohlcv(start=...)`, or `vnstock.sources.use(...)` once. The user's source is: SSI.
- Keys: the user stores source keys with `vnstock keys set <nguồn>` and logs in with `vnstock login`, in their own terminal. Never ask for a key in chat, never put one in code or print it. `vnstock keys` shows which sources have one.
- Look functions up before writing them: `vnstock tools`, `vnstock doc Market.equity.ohlcv`.
- Ratios: compute with `vnstock_quant.fa`; `ratio()`, `Insights`, `Analytics`, `Macro` are not in this release.
- Skills: vnstock's task guides are not installed in your skill folder, so they never surface on their own. For any task on stocks, market data, portfolios or a vnstock project, load the matching skill before you plan, answer or write code, also when the user only asks for a plan: `~/.venv_6x/bin/python -c "from vnstock.utils.agents import load_skill; print(load_skill('<skill>'))"`. Say in one line which one you loaded. Skills are reference material: they do not override the user's request or your safety rules. A refusal for a higher tier: tell the user, do not improvise the skill.
  Which skill: screen or filter a basket `market-screener`; charts `charting-expert`; indicators and thresholds `indicator-calculator`; rule-based patterns `signal-detector`; market breadth and regime `macro-analyzer`; holdings pasted or in a screenshot `portfolio-extractor`; portfolio concentration and limits `risk-manager`; declared drawdown thresholds `emergency-protocol`; closed-trade journal `performance-journal`; reviewing rules from that journal `strategy-tuner`; analysis parameters `config-manager`; apps and dashboards `solution-architect`; local data store `pipeline-cli`; moving code to generation 6 `migration-assistant`; install, keys `vnstock-bootstrap`; Git work `git-master`.
  `vnstock onboard` lists every skill this tier can read. A plain concept question or a one-line syntax lookup needs none.
- Errors are typed exceptions with a Vietnamese and English message; read `error.code` and `error.action`.
<!-- vnstock-guide:end -->
