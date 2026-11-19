# Interview notes: questions you should expect, and honest answers

**1. What problem does it solve?**
Teams are afraid to deploy agents because of prompt injection, data leaks, over-privileged tools and made-up answers.
The project puts a firewall at each trust boundary of an agent system and measures what each layer contributes.

**2. Why five layers instead of one guardrail on the chat input?**
Real attacks do not only arrive through the chat box. Documents the agent retrieves (indirect injection), tool outputs, and the model's own answer are
separate trust boundaries. Each has its own failure mode, so each gets its own control.

**3. Which layer matters most?**
The tool layer: authorization enforced in code. In my measurements it removes most of the risk on its own. Look at the per-layer table in the report for the current numbers.
The other layers overlap on purpose; defence in depth is the design, and the ablations show how much they overlap.

**4. What is "unauthorized tool executions" and why did you add it?**
For attacks by an unprivileged user, did a sensitive tool (look up a record, reset access) actually run? A system can redact every leak in the answer and still run
the action. Output-based attack success cannot see that, so I measure both.

**5. How do you know the firewall is not just blocking everything?**
A separate benign set measures false positives. The report lists every benign request that was blocked and why.
My first run found two (a routing mistake and a grounding bug); I fixed both and re-ran. I say so in the write-up.

**6. Is the held-out set really held out?**
It was written after the firewall was frozen and never used to tune patterns or thresholds. One of its benign requests exposed a bug (step labels counted as facts),
and I fixed it in a general way, so that set is slightly less pristine than it started. I disclose that instead of hiding it.

**7. What does "paired replay" mean?**
Model replies are cached by prompt. Every configuration receives the identical reply to an identical prompt, so differences between configurations come from the firewall,
not from the model's randomness. It does not remove sampling noise of the baseline itself, which is why I show confidence intervals.

**8. Why fail closed? What does it cost?**
If a guard errors or times out, the safe action is to block. The cost is availability: a classifier outage blocks traffic. For a security control that is the right default,
and it is documented. In the measurement harness a failed guard stops the run instead of counting as a block, so infrastructure problems cannot inflate results.

**9. Why not just use NeMo Guardrails or Guardrails AI?**
They are good, and the layer interface here (`allow`, `block`, `modify`, reason, score) is compatible with swapping them in. I built the layers myself to control the trust boundaries
(especially context and tools) and to make every decision measurable and auditable. Presidio could replace my regex PII detector the same way.

**10. How does the Prompt Guard classifier perform and what does it cost?**
It catches paraphrased and non-English injections that regexes miss, at the price of about a second of latency per scanned request and a small false-positive rate.
Scores are cached per text, and quarantined chunks can be released by an admin.

**11. What would you do next for production?**
Real authentication (SSO or signed tokens) instead of a dropdown, per-user access control on retrieved documents, multi-turn attack tests,
an LLM-judge grounding check, persistent audit storage, rate limiting per user, and monitoring of block rates.

**12. What are the limits of your evidence?**
One small model, small test sets written by the author, one run per configuration. The numbers show a clear effect, but they are not a guarantee, and the report says what still gets through.

**13. Tell me about a bug you found while measuring.**
Three good ones: the first detector for "hallucination" reported 100% because of a curly apostrophe and unlisted refusal phrasings, which I only noticed by reading the raw answers;
an infrastructure failure could be counted as a firewall block, so I made it stop the run; and an agent without a "none" tool picked a privileged tool for a harmless question, which the
firewall correctly blocked but which hurt a real user.
