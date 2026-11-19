# Deploying Guardrail Agents (Step 9)

You will end with a public URL where anyone can attack the helpdesk agent with the firewall off and on.
Everything on it is simulated (fake employees, fake tools), and the demo is protected against abuse.

## 0. What protects a public demo

| Risk | Protection |
|---|---|
| A stranger turns the firewall off for everyone | The toggle is **per request** (a context variable). It cannot affect another visitor |
| Someone drains your Groq quota | Per-visitor limits (6 per minute, 60 per day) and a **global daily budget** (requests and tokens) |
| An unsafe deployment | `APP_ENV=production` **refuses to start** without an `ADMIN_TOKEN` of 24+ characters or with the firewall disabled |
| Open admin or webhook endpoints | Admin routes need the token (503 if unset); the webhook is closed in production unless `WEBHOOK_SECRET` is set |
| Something goes wrong | Kill switch: `POST /admin/demo/off` (or set `DEMO_ENABLED=false`) |
| API docs expose the surface | `/docs` and `/openapi.json` are off in production |

## 1. Prepare (10 minutes)

1. **Rotate your Groq key.** console.groq.com, API Keys: delete the old one, create a new one, click Copy. This key will live only in the host's secret settings.
2. **Generate an admin token** and keep it in your password manager:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. **Run the tests:** `python -m pytest -q` (expect `99 passed`).
4. **Try production mode locally** (fake model, no key needed):
   ```powershell
   $env:APP_ENV="production"; $env:ADMIN_TOKEN="paste-a-long-token-here-24-plus"; $env:LLM_PROVIDER="mock"
   uvicorn app.api.main:app --port 8000
   ```
   Open http://localhost:8000 . Then clear the variables: `Remove-Item Env:APP_ENV, Env:ADMIN_TOKEN, Env:LLM_PROVIDER`.
5. *(Optional, needs Docker Desktop)* `docker build -t guardrail .` then
   `docker run -p 7860:7860 -e ADMIN_TOKEN=paste-a-long-token-here-24-plus -e LLM_PROVIDER=mock guardrail`.

## 2. Put the code on GitHub

1. Create a free account at github.com, then **New repository** (name `guardrail-agents`, no README, no .gitignore).
2. Check that no secret is tracked. This must list only `.env.example`:
   ```powershell
   git ls-files | findstr /i "\.env"
   ```
3. Push (replace YOUR-USER):
   ```powershell
   git add .
   git commit -m "Step 9: deployment"
   git branch -M main
   git remote add origin https://github.com/YOUR-USER/guardrail-agents.git
   git push -u origin main
   ```
   If the push asks for a password, GitHub needs a Personal Access Token (Settings, Developer settings) or sign-in through VS Code (Accounts menu, bottom left).

## 3a. Deploy on Render

1. render.com, sign in with GitHub, **New**, **Web Service**, pick the repo.
2. **Runtime: Docker.** Plan: **Free**. Health check path: `/health`.
3. **Environment variables** (Advanced):

   | Key | Value |
   |---|---|
   | `APP_ENV` | `production` |
   | `ADMIN_TOKEN` | your generated token |
   | `OPENAI_API_KEY` | the NEW Groq key |
   | `LLM_PROVIDER` | `openai` |
   | `OPENAI_BASE_URL` | `https://api.groq.com/openai/v1` |
   | `LLM_MODEL` | `openai/gpt-oss-20b` |
   | `LLM_REASONING_EFFORT` | `low` |
   | `TRUST_PROXY` | `true` |
   | `DEMO_DAILY_TOKENS` | `100000` |
   | `DEMO_DAILY_REQUESTS` | `300` |

   (`render.yaml` in the repo lists the same values if you prefer a Blueprint.)
4. **Create Web Service.** The first build takes a few minutes. Your URL looks like `https://guardrail-agents-xxxx.onrender.com`.

Free instances sleep after inactivity, so the first visit can take about a minute. Plans and limits change; check Render's pricing page.

## 3b. Deploy on Hugging Face Spaces (alternative, no GitHub needed)

1. huggingface.co, **New Space**, SDK **Docker**, visibility Public.
2. Add this block to the **top of README.md in the Space repo only**:
   ```
   ---
   title: Guardrail Agents
   sdk: docker
   app_port: 7860
   ---
   ```
3. Push the project files to the Space's git repository (the page shows the commands).
4. Space **Settings, Variables and secrets:** add `ADMIN_TOKEN` and `OPENAI_API_KEY` as **secrets**, and the other keys from the table above as variables.

## 4. After it is live: smoke test (replace the URL)

```powershell
$base = "https://YOUR-URL"
Invoke-RestMethod "$base/health"
$body = '{"persona":"mallory","message":"lookup employee bob salary","firewall":false}'
Invoke-RestMethod -Method Post "$base/demo/chat" -ContentType "application/json" -Body $body
```
Expect a `tool_call` and the fake salary 92000 (firewall off). Repeat with `"firewall":true`: expect `blocked`.
Then open `$base/` in a browser, click **Compare**, and open `$base/dashboard`.

**Kill switch** (keep this handy):
```powershell
Invoke-RestMethod -Method Post "$base/admin/demo/off" -Headers @{"X-Admin-Token"="YOUR-TOKEN"}
```
Use `/on` to re-enable.

## 5. Things to know

- **The audit log is in `/tmp` and resets on every restart or redeploy** on free hosts. The dashboard shows only recent traffic. A paid disk or an external database would make it permanent.
- **Prompt Guard runs on every request** through your Groq key and fails closed. If Groq throttles it, visitors see blocked requests, not wrong answers.
- **Identity in the demo is a dropdown** (alice, mallory, bob, carol). That is fine for a simulation; a real system takes identity from verified authentication (SSO or a signed token).
- Watch your Groq usage page for a few days. Lower `DEMO_DAILY_TOKENS` if it climbs too fast.
- Delete or rotate the Groq key when you take the demo down.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Container exits immediately: `APP_ENV=production requires ADMIN_TOKEN...` | Deliberate: unsafe configuration | Set `ADMIN_TOKEN` (24+ characters) as a secret |
| Page loads but every message says the daily budget is used up | Global limits reached | Wait for tomorrow, or raise `DEMO_DAILY_*` |
| Everything is "blocked" with `guard error` | Groq throttling or the key is wrong | Check the key and the Groq usage page |
| 401 from `/approvals` | Wrong `X-Admin-Token` | Use the exact value stored in the host's secrets |
| First request very slow | Free instance waking up | Wait about a minute |
| Build fails on `COPY data` | Wrong folder | Deploy from the project root (where `Dockerfile` is) |
