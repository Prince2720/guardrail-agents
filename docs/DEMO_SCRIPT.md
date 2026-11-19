# Demo script (2 minutes) and how to present the project

## Before you record (10 minutes)

- Close other tabs and notifications. Use a clean browser window at 100% zoom.
- Clear your terminals (`cls`) and make sure **no `.env` file or API key is visible anywhere**.
- Have these open in tabs: the demo page `/`, the dashboard `/dashboard`, `redteam/results/REPORT.md` (rendered), and the GitHub repo.
- Use the live URL if it is deployed; otherwise run locally with the real model (`uvicorn app.api.main:app`) so answers look natural, not `[mock answer]`.
- **Use the scenario tickets, not free typing.** A typo such as "Alce" makes the lookup return "not found", so nothing dramatic shows. Do a dry run of every example first; a real model can word things differently each time.
- Recorder: **Win + G** (Xbox Game Bar) or OBS Studio. 1080p, microphone check, one take is fine.

## The script

| Time | On screen | Say |
|---|---|---|
| 0:00 | Demo page, headline "Same attack, two systems." | "Companies are afraid to put AI agents into production because they can be tricked into leaking data or taking actions they shouldn't. I built an IT/HR helpdesk agent with a five-gate firewall, and I measured whether it works." |
| 0:15 | Click the **Ask a normal question** ticket | "A normal question works on both sides. A good firewall stays out of the way." |
| 0:30 | Click **Read a colleague's salary** (Mallory) | "One click sends the same attack to both systems. On the left, with no protection, the agent ran the lookup: that red line is a real tool call. On the right, the request travels the same path and the Tools gate stamps it 'Stopped here': authorization is enforced in code, not left to the model's good manners." |
| 0:55 | Click **Tell it to ignore its rules** | "A classic injection. It is stopped at the very first gate, so every later gate says 'Not reached'." |
| 1:10 | Click **Plant an order in a document**, then open the Dashboard | "Here the attack hides in a document the agent reads. The Context gate removes it before the model sees it; the amber note says so. An admin can review quarantined documents in this queue." |
| 1:25 | Click **Admin resets a password** | "Even a legitimate admin action is not simply executed: the Tools gate holds it until a human approves." |
| 1:35 | Dashboard: counts, "Audit log intact" | "Every decision goes into a tamper-evident, hash-chained audit log, and the dashboard shows what each gate is stopping." |
| 1:45 | The sentence under the headline, then the README results table | "I ran a red-team suite plus a held-out set with and without the firewall, replaying the model's answers so the comparison is fair. Attack success fell from X to Y, unauthorized tool executions from A to B, and this is what it cost in false positives. The report also lists what still gets through." |
| 1:58 | GitHub repo | "Code, tests, the experiment and the deployment guide are in the repo. Thanks for watching." |

Fill in X, Y, A, B from `python -m redteam.update_readme --bullets` so the numbers you say match the report.

## Say this, never this

- Say: "reduced", "in my measurements", "on this test set", "here is what still gets through".
- Never say: "100% secure", "solves prompt injection", "unhackable". The report itself says the opposite, and a reviewer will check.

## Post / profile text (edit the numbers)

> I built an AI helpdesk agent behind a five-layer firewall (ingress, context, tools, egress, audit) and measured it instead of just claiming it works.
> Red-team attack success fell from X% to Y%, unauthorized tool executions from A% to B%, with N false positives on M benign requests.
> The biggest lesson: a firewall that only hides leaks can look safe while privileged actions still run, so I track unauthorized executions separately.
> Live demo, code and the full report with its limitations: <link>

**Resume bullets** with your real numbers: `python -m redteam.update_readme --bullets`.

## GitHub polish checklist

- [ ] README top shows the demo screenshot (`docs/demo.png`), the architecture diagram and the results table
- [ ] `python -m redteam.update_readme` run after the final experiment
- [ ] Repository description and topics: `llm-security`, `guardrails`, `langgraph`, `fastapi`, `prompt-injection`, `ai-safety`
- [ ] `git ls-files | findstr /i "\.env"` lists only `.env.example`
- [ ] Live demo link in the README and in the repo's "About" box
- [ ] Pin the repository on your GitHub profile
