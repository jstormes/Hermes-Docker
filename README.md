# Hermes-Docker

Quickly stand up [Nous Research's Hermes](https://github.com/NousResearch/Hermes) agent in Docker, wired to the self-hosted [`llm.stormes.net`](#the-llm-endpoint--llmstormesnet) LLM fleet.

This repo bundles a `Dockerfile` (Hermes base image + the system/Python tools its skills need), a single-container `docker-compose.yml` (s6-supervised gateway + dashboard) that runs on Docker Desktop (Windows/macOS) and native Linux, and ready-to-use agent configs.

---

## Contents

- [Quick start](#quick-start)
  - [What's in this repo](#whats-in-this-repo)
- [The agent's workspace](#the-agents-workspace)
- [Using Claude Code in the container](#using-claude-code-in-the-container)
- [The LLM endpoint — `llm.stormes.net`](#the-llm-endpoint--llmstormesnet)
  - [Models](#models)
- [Hermes configuration](#hermes-configuration)
- [Model recommendations for Hermes](#model-recommendations-for-hermes)
  - [The core strategy: speed vs. thinking](#the-core-strategy-speed-vs-thinking)
  - [Task-by-task recommendations](#task-by-task-recommendations)
  - [Server-specific fan-out limits](#server-specific-fan-out-limits)
  - [Setting up profiles and fan-out caps](#setting-up-profiles-and-fan-out-caps)
  - [Summary of recommendations](#summary-of-recommendations)
- [Reasoning-loop mitigation](#reasoning-loop-mitigation)
  - [The problem](#the-problem)
  - [The mitigation: `thinking_budget_tokens`](#the-mitigation-thinking_budget_tokens)
  - [How it reaches each Hermes model slot](#how-it-reaches-each-hermes-model-slot)
  - [What to change in `.hermes/config.yaml`](#what-to-change-in-hermesconfigyaml)
  - [Tuning notes](#tuning-notes)
- [Benchmarks](#benchmarks)
  - [Solo decode (tokens/sec)](#solo-decode-tokenssec)
  - [Solo prefill (tokens/sec — how fast your prompt is ingested)](#solo-prefill-tokenssec--how-fast-your-prompt-is-ingested)
  - [Concurrency — aggregate decode (tokens/sec across N simultaneous requests)](#concurrency--aggregate-decode-tokenssec-across-n-simultaneous-requests)
- [Usage notes (important)](#usage-notes-important)
- [Suggested sampler settings (model-card defaults)](#suggested-sampler-settings-model-card-defaults)
- [How it's served (the stack)](#how-its-served-the-stack)
- [Etiquette & limits](#etiquette--limits)

---

## Quick start

**Prerequisites:** Docker Desktop (Windows/macOS) or Docker Engine + Compose. An `llm.stormes.net` API key (ask the endpoint owner — see [Etiquette & limits](#etiquette--limits)).

1. **Fork this repo to a private repo, then clone your fork.** You'll be committing your own `.hermes/config.yaml` and tweaking the compose/Dockerfile — keep that in a **private** fork so your settings (and anything that ends up near your API key) never land in a public repo.

   On GitHub, use **Fork** (or create a new private repo and push this one into it), set its visibility to **Private**, then:

   ```bash
   git clone git@github.com:<your-user>/Hermes-Docker.git
   cd Hermes-Docker
   ```

2. **Set up your `.env`.** Copy the template and fill it in — Docker Compose loads this file automatically and injects the values into the container, so your secrets stay out of `config.yaml` and out of git (`.env` is git-ignored). Do this **before** the wizard so it can pre-fill from these values.

   ```bash
   cp .env.example .env      # then edit .env
   ```

   At minimum set `OPENAI_API_KEY` (your `llm.stormes.net` bearer key). The template also includes `OPENAI_BASE_URL` (pre-filled to the fleet endpoint — pre-fills the wizard) and an optional `CLAUDE_CODE_OAUTH_TOKEN` ([use Claude Code in the container](#using-claude-code-in-the-container)). See [Hermes configuration → API key](#hermes-configuration) for the full rationale.

3. **Build the image:**

   ```bash
   docker compose build
   ```

4. **Run Hermes' setup wizard.** Hermes ships an interactive wizard (`hermes setup`) that writes `config.yaml` for you — don't hand-author it. Run it through the `hermes` service so it writes into the mounted `.hermes` volume (the compose file mounts `./.hermes` → `/opt/data`, which is where the container reads its config). Run this **before** starting the stack (step 6) so the one-off wizard container doesn't contend with the running gateway for the data volume:

   ```bash
   docker compose run --rm -it hermes setup
   ```

   The wizard is interactive — it must run in a real terminal (it can't be driven non-interactively). When it asks for a provider/model, point it at the fleet:

   | Wizard prompt | Answer |
   |---|---|
   | Provider type | **Custom (direct API)** — labelled "Custom / OpenAI-compatible" in some versions |
   | Base URL | `https://llm.stormes.net/v1` (pre-filled if you set `OPENAI_BASE_URL` in `.env` — just press Enter) |
   | API key | your `llm.stormes.net` bearer key (leave blank if it's in `.env`) |
   | Default model | `Qwen3.6-35B-A3B-Q8-8060S` |

   (Exact prompts vary by Hermes version. You can re-run the wizard, or use `hermes model` / `hermes config set`, at any time to change these.) This produces `.hermes/config.yaml` in the repo.

   > **Tip:** because you filled in `.env` in step 2, the wizard reads `OPENAI_BASE_URL` / `OPENAI_API_KEY` from the environment and offers them as the bracketed defaults — press Enter at the base-URL prompt to accept, and leave the key prompt blank so the secret stays in `.env` instead of `config.yaml`.

   > **Note:** the wizard may still write `api_key:` directly into `.hermes/config.yaml`. If it does, delete that line — the `OPENAI_API_KEY` from `.env` takes precedence, and you want the secret out of the YAML.

5. **(Recommended) Refine the generated config.** Open `.hermes/config.yaml` and add the fleet-specific bits the wizard doesn't cover: per-task model routing (see [Hermes configuration](#hermes-configuration) and [Model recommendations for Hermes](#model-recommendations-for-hermes)) and the `thinking_budget_tokens` / `custom_providers` settings that stop the Qwen models from looping (see [Reasoning-loop mitigation](#reasoning-loop-mitigation)).

6. **Start Hermes:**

   ```bash
   docker compose up -d
   ```

   This starts a single `hermes` container. The base image uses s6-overlay supervision: one `/init` process supervises both the gateway (agent runtime) and the dashboard (web UI + embedded chat) inside that container. They must share one container — running two against the same `.hermes` data volume collides on the gateway runtime lock.

   > **Note:** the first startup takes a few minutes while the images build and the services initialize. Subsequent starts are much faster.

7. **Open the dashboard:** <http://127.0.0.1:9119>

   The dashboard is published to **host loopback only** (`127.0.0.1:9119`). The embedded chat tab gives a full agent session — shell and file access to the mounted repo — so keep it on loopback.

8. **Stop / rebuild:**

   ```bash
   docker compose down          # stop
   docker compose up -d --build  # rebuild after edits
   ```

> ⚠️ **Security:** the dashboard runs with `--insecure` (no auth), which lets the embedded chat work behind Docker Desktop's bridge NAT (upstream handles the WebSocket loopback gate natively — no patch needed). This means **anyone who can reach port 9119 gets a full agent session**. The `127.0.0.1:` prefix on the port mapping is the only thing keeping that off your LAN — **never** change it to `9119:9119` or `0.0.0.0:...`. For network exposure, switch to gated OAuth mode instead.

### What's in this repo

| File | Purpose |
|---|---|
| `Dockerfile` | Hermes base image + tmux, ffmpeg, espeak-ng, Chromium, Node, `jq`, the Claude Code CLI, and Python extras (`ddgs`, `scipy`) that Hermes skills detect at import time. |
| `docker-compose.yml` | Cross-platform compose (Docker Desktop on Windows/macOS + native Linux). Publishes explicit ports instead of `network_mode: host` (unsupported on Docker Desktop). Defines a single `hermes` service; the image's s6-overlay supervises the gateway + dashboard inside it, with the dashboard toggled on via `HERMES_DASHBOARD=1`. |
| `.hermes/` | Your Hermes data + `config.yaml` (mounted into the container at `/opt/data`; generated by `hermes setup` — see [Quick start](#quick-start) step 4). The API key lives in `.hermes/.env`. |
| `projects/` | The agent's workspace. Bind-mounted to `/projects` in the container, which is set as the default working directory — new files the agent creates land here and show up on your host. See [The agent's workspace](#the-agents-workspace). Auto-created empty on first `up`. |
| `.env` / `.env.example` | Project-root env file Docker Compose loads automatically; holds `OPENAI_API_KEY`, `OPENAI_BASE_URL`, the optional `CLAUDE_CODE_OAUTH_TOKEN`, and any other secret env vars. Copy the example to `.env` and fill it in. Git-ignored. |
| `.gitignore` | Keeps secrets (`.env`, `.hermes/.env`) and runtime state out of git. |

---

## The agent's workspace

New files the agent creates land in **`/projects`** inside the container, which is bind-mounted to **`./projects`** on your host — so the agent's work shows up directly in this repo's `projects/` folder (and vice-versa: drop files there to share them with the agent).

This is wired up in `docker-compose.yml`:

| Setting | Effect |
|---|---|
| `- ./projects/:/projects` (volume) | Maps host `./projects` ↔ container `/projects`. |
| `working_dir: /projects` | `docker compose ... exec hermes …` and the chat shell start in `/projects`. |
| `TERMINAL_CWD=/projects` | The agent's shell/file tools run in `/projects` (the gateway bridges this from the `terminal.cwd` config key). |
| `HERMES_CWD=/projects` | The dashboard's embedded chat treats `/projects` as the project directory. |

> **Note:** the container's home directory (`/opt/data`, where `config.yaml` and session state live) **can't** be relocated — the base image hardcodes `HOME=/opt/data` in its supervised services. `/projects` is a separate workspace, which is why these settings target the working directory rather than `HOME`.

> **Startup warning:** Hermes prints a benign `⚠ TERMINAL_CWD=/projects found in .env …` line on boot because the canonical place for this setting is `config.yaml`. To silence it, add the following to `.hermes/config.yaml` (after running the setup wizard):
>
> ```yaml
> terminal:
>   cwd: /projects
> ```

---

## Using Claude Code in the container

The image ships the [Claude Code](https://claude.com/claude-code) CLI (installed in the `Dockerfile`), so you can run `claude` inside the container — e.g. from the dashboard's embedded chat shell or via `docker compose exec hermes claude`.

To authenticate it as your **logged-in Claude Pro/Max account** without a browser login inside Docker, use a long-lived OAuth token:

1. On your host (where a browser is available), generate the token:

   ```bash
   claude setup-token
   ```

   This opens a browser, you authorize with your account, and it prints a ~1-year token. Requires a Pro/Max/Team/Enterprise subscription.

2. Put it in the project-root `.env` (git-ignored):

   ```bash
   # .env
   CLAUDE_CODE_OAUTH_TOKEN=<token from setup-token>
   ```

3. Recreate the container so Compose injects it:

   ```bash
   docker compose up -d
   ```

`claude` inside the container now picks up `CLAUDE_CODE_OAUTH_TOKEN` from the environment — no `/login` needed.

> **Notes.** The token is inference-scoped (fine for normal use; it can't establish Remote Control sessions), and `claude --bare` ignores it. This is independent of `OPENAI_API_KEY` — that key drives the Hermes fleet and Claude Code ignores it, so the two coexist. Treat the token like a password.

---

## The LLM endpoint — `llm.stormes.net`

A small fleet of self-hosted, open-weight models served behind **one OpenAI-compatible HTTPS endpoint**. Point any OpenAI-style client at it, set your bearer key, and pick a model by name.

```
Base URL:  https://llm.stormes.net/v1
Auth:      Authorization: Bearer <YOUR_API_KEY>
API:       OpenAI-compatible (/v1/models, /v1/chat/completions, /v1/completions)
TLS:       Let's Encrypt (real cert)
Streaming: supported ("stream": true)
```

> **Your key is handed to you separately — keep it secret.** It's a single shared key with no hard rate limit, so please be considerate (see [Etiquette](#etiquette--limits)). Five bad-auth attempts in 10 minutes gets your IP auto-banned for an hour, so don't retry-spam a wrong key.

### Models

All models are open-weight, served by [llama.cpp](https://github.com/ggml-org/llama.cpp). Four of the five are **vision-capable** (accept images). Pick by the trade-off you want — quality vs. speed vs. context.

| Model id | GPU | Type | Params | Quant | Context | Vision | Concurrency |
|---|---|---|---|---|---|---|---|
| `Qwen3.6-35B-A3B-Q8-8060S` | Radeon 8060S (Strix Halo) | MoE (~3B active) | 35B | Q8_0 | 256K | ✓ | 4 slots |
| `Gemma-4-26B-A4B-Q8-8060S` | Radeon 8060S (Strix Halo) | MoE (~4B active) | 26B | Q8_0 | 256K | ✓ | 4 slots |
| `Qwen3.6-27B-Q8-R9700` | 2× Radeon AI PRO R9700 | dense | 27B | Q8_0 | 160K | ✓ | 2 slots |
| `Qwen3.6-35B-A3B-Q8-780M` | Radeon 780M (Phoenix) | MoE (~3B active) | 35B | Q8_0 | 256K | ✓ | 4 slots |
| `Qwen3.5-9B-Q4-780M` | Radeon 780M (Phoenix) | dense | 9B | Q4_K_M | 256K | ✗ (text only) | 1 slot |

**Which one should I use?**

- **`Qwen3.6-35B-A3B-Q8-8060S` — the default pick.** Fastest decode in the fleet and a strong all-rounder (reasoning, code, vision). Handles several parallel requests well.
- **`Gemma-4-26B-A4B-Q8-8060S`** — great for style/tone, OCR, charts, and UI-screenshot tasks; also the fastest at chewing through long prompts. Shares its GPU with the model above, so heavy traffic to both slows both.
- **`Qwen3.6-27B-Q8-R9700`** — a dense (non-MoE) model on the big dual-GPU box. Slower per token but a different model character; this one also backs the endpoint's "house" default. Best when you want the dense Qwen specifically.
- **`Qwen3.6-35B-A3B-Q8-780M`** — same weights/quality as the top Qwen but on a smaller GPU (~half the speed). Good overflow/background node when the fast box is busy.
- **`Qwen3.5-9B-Q4-780M`** — lightweight, text-only, cheapest to run. Fine for quick/bulk text where you don't need the big models.

#### Every callable model id

The complete list — pick any of these as the `model` field. The `-code` / `-fast` suffixes are **ready-made profiles** applied server-side (sampler + thinking toggle); the base id is the general/thinking default. You can still override any sampler value per request.

| Model id | Profile | Thinking | Default sampler | Notes |
|---|---|---|---|---|
| `Qwen3.6-35B-A3B-Q8-8060S` | general *(default)* | on | temp 1.0 | Best "fast" model |
| `Qwen3.6-35B-A3B-Q8-8060S-code` | coding — tighter | on | temp 0.6 | |
| `Qwen3.6-35B-A3B-Q8-8060S-fast` | quick — direct | **off** | temp 0.7 | Fastest model |
| `Gemma-4-26B-A4B-Q8-8060S` | general *(default)* | on | temp 1.0, top_k 64 | |
| `Gemma-4-26B-A4B-Q8-8060S-code` | coding — tighter | on | temp 0.6, top_k 64 | Best for reviewing code created by Qwen |
| `Gemma-4-26B-A4B-Q8-8060S-fast` | quick — direct | **off** | temp 1.0, top_k 64 | |
| `Qwen3.6-27B-Q8-R9700` | general *(default)* | on | temp 1.0 | |
| `Qwen3.6-27B-Q8-R9700-code` | coding — tighter | on | temp 0.6 | Best coder |
| `Qwen3.6-27B-Q8-R9700-fast` | quick — direct | **off** | temp 0.7 | |
| `Qwen3.6-35B-A3B-Q8-780M` | general *(default)* | on | temp 1.0 | Overflow/background tier |
| `Qwen3.6-35B-A3B-Q8-780M-code` | coding — tighter | on | temp 0.6 | Overflow/background tier |
| `Qwen3.6-35B-A3B-Q8-780M-fast` | quick — direct | **off** | temp 0.7 | Overflow/background tier |
| `Qwen3.5-9B-Q4-780M` | light, text-only *(no variants)* | n/a | temp 1.0 | Overflow/background tier |

Hardware / context / vision per base model are in the table above (the `-code` / `-fast` variants share their base model's GPU, context window, and vision support). `GET /v1/models` returns the same list if you'd rather pull it programmatically.

> **Note on context:** all models accept very long inputs (up to **262,144 tokens**, except `Qwen3.6-27B-Q8-R9700` at **160K**). Decode speed is roughly flat with context; *prefill* (reading your prompt) is what costs time on huge inputs.

---

## Hermes configuration

The fastest way to create a valid config is Hermes' own setup wizard — `docker compose run --rm -it hermes setup` ([Quick start](#quick-start) step 4). It writes `.hermes/config.yaml` for you; the blocks below are what to set/refine afterward.

Hermes uses a custom (OpenAI-compatible) provider pointed at the endpoint. In `.hermes/config.yaml` (mounted into the container — see [Quick start](#quick-start)):

```yaml
default: Qwen3.6-35B-A3B-Q8-8060S
provider: custom                     # "custom" = any OpenAI-compatible endpoint
base_url: https://llm.stormes.net/v1
# api_key is NOT set here — leave it out and Hermes reads it from the
# environment / .hermes/.env (see "API key" below). Keep secrets out of config.
session_id_header_name: X-Session-ID

# Optional: route Hermes's helper tasks to cheaper / specialized models
auxiliary:
  vision:
    model: Qwen3.6-35B-A3B-Q8-8060S
  web_extract:
    model: Qwen3.6-35B-A3B-Q8-780M-fast   # -fast = thinking disabled server-side
  compression:
    model: Qwen3.6-35B-A3B-Q8-780M-fast
  title_generation:
    model: Gemma-4-26B-A4B-Q8-8060S
```

**API key (via environment / `.env`).** Hermes reads provider keys from the process environment, and **the environment takes precedence over `config.yaml`** — so the key never has to land in the YAML (or in git). Don't hardcode `api_key:` and don't try `${VAR}` interpolation in the YAML — this Hermes version doesn't expand it; it falls back to the provider's env var instead. For a custom / OpenAI-compatible provider that env var is `OPENAI_API_KEY`.

**Recommended: the project-root `.env`.** Docker Compose reads `.env` (next to the compose file) automatically and injects it into the container — set up in [Quick start](#quick-start) step 2. It holds:

```bash
# .env   (project root — git-ignored)
OPENAI_API_KEY=<your-llm.stormes.net-bearer-key>
OPENAI_BASE_URL=https://llm.stormes.net/v1   # optional; also pre-fills the setup wizard
```

The key is forwarded to the provider as a standard `Authorization: Bearer` header.

**Alternative: `.hermes/.env`.** Hermes also reads `~/.hermes/.env`, which in this Docker setup is the already-mounted `.hermes/.env` (the `.hermes` volume maps to the container's Hermes home). The wizard writes this for you when you paste the key. Either location works — the project-root `.env` is just less to think about.

**Any other secret env var** belongs in `.env` too (extra keys, tokens, local overrides). To pass one into the container, also reference it in `docker-compose.yml` under the `hermes` service's `environment:` (e.g. `- MY_VAR=${MY_VAR:-}`). Both `.env` and `.hermes/.env` are git-ignored (see [`.gitignore`](./.gitignore)); keep it that way even in a private fork.

See [Model recommendations for Hermes](#model-recommendations-for-hermes) for which model to put on each auxiliary slot, and [Reasoning-loop mitigation](#reasoning-loop-mitigation) for the `thinking_budget_tokens` / `custom_providers` settings that stop the Qwen models from looping.

---

## Model recommendations for Hermes

Based on the fleet inventory above and how Hermes auxiliary tasks actually behave.

### The core strategy: speed vs. thinking

Hermes auxiliary tasks generally fall into two categories: those that need **speed** (titles, searching sessions, extracting web pages) and those that need **reasoning quality** (compressing a long chat history).

The "9B" model (`Qwen3.5-9B-Q4-780M`) is text-only but has the slowest decode speed (~14 t/s). Using it for high-volume tasks like search or extraction creates bottlenecks because the main agent has to wait longer. Conversely, the MoE models (`35B-A3B` and `26B-A4B`) only activate ~3-4B parameters per token while running all their weights on Strix Halo hardware, giving them a massive speed advantage (~50+ t/s).

**Key config flags:**

- **`-fast` suffix:** Disables the "thinking" (reasoning trace) server-side. Use this for simple tasks where you want an instant answer without the model writing out its internal monologue (which eats up your `max_tokens` budget and time).
- **Thinking ON (default):** Leaves the reasoning block enabled. Best for complex logic or summarization, but use a generous `max_tokens` so the reasoning trace doesn't cut off the actual response.

### Task-by-task recommendations

**1. Session search & web extract (prioritize speed)**

- **Model:** `Qwen3.6-35B-A3B-Q8-8060S-fast`
- **Why:** These tasks happen constantly. You need the MoE architecture's high throughput (~50+ t/s). Because they are simple extraction or formatting jobs, the `-fast` (non-thinking) variant gives you a direct answer instantly without burning tokens on a reasoning trace.
- **Alternative:** `Gemma-4-26B-A4B-Q8-8060S-fast` is also excellent and has even faster prefill speeds for long pages.

**2. Title generation (prioritize speed)**

- **Model:** `Gemma-4-26B-A4B-Q8-8060S-fast`
- **Why:** Titles are one or two lines of text. You don't need deep reasoning to summarize a chat topic; you just need the model to be fast so the user isn't staring at a loading screen. Gemma is particularly good at style and tone, which helps for title generation.

**3. Compression (prioritize quality)**

- **Model:** `Gemma-4-26B-A4B-Q8-8060S` (Thinking ON)
- **Why:** Compression is the most logic-heavy task — Hermes asks it to read a massive context window and decide what to keep and what to throw away. It genuinely benefits from the "thinking" block to process that information before generating the summary. Gemma 4 has shown strong results with long-context summarization/structure.
- *Note:* Ensure your `max_tokens` for compression is set generously (e.g., >512) so the model's internal reasoning doesn't consume your entire token budget.

**4. Vision (prioritize accuracy for OCR/screenshots)**

- **Model:** `Gemma-4-26B-A4B-Q8-8060S`
- **Why:** Gemma is "great for OCR, charts, and UI-screenshot tasks." It generally handles visual grounding slightly better than the Qwen models in these specific contexts.

### Server-specific fan-out limits

Because every model runs on a specific node with its own systemd service configuration (specifically the `-np` or parallel slot count), your Hermes fan-out limits must match the underlying hardware capacity. Setting `delegation.max_concurrent_children` higher than the server's slot limit will cause "context full" errors and queueing.

| Model ID | Host / Hardware | Max Slots (`-np`) | Recommended Fan-Out | Rationale |
|---|---|---|---|---|
| `Qwen3.6-27B-Q8-R9700` (and `-code`) | crypto1 / 2× R9700 | **2** | **2** | Dense model; production service is locked to `llama-9700-mtp-q8` with 2 slots. Exceeding this causes context rejection. |
| `Qwen3.6-35B-A3B-Q8-8060S` (and `-code`, `-fast`) | ai / Strix Halo | **4** | **3** | MoE architecture (~3B active params). Shares GPU with Gemma; 3 provides a safety margin against memory pressure. |
| `Gemma-4-26B-A4B-Q8-8060S` (and `-code`, `-fast`) | ai / Strix Halo | **4** | **3** | MoE architecture (~4B active params). Shares GPU with the 35B Qwen; same safety margin applies. |
| `Qwen3.6-35B-A3B-Q8-780M` (and variants) | ai4 / 780M | **4** | **2** | MoE (~3B active), but the node has only 64GB VRAM. Capping at 2 ensures faster per-request throughput. |
| `Qwen3.5-9B-Q4-780M` (text-only) | ai3 / 780M | **1** | **1** | Dense model; systemd service is locked to `-np 1`. Any higher will fail. |

### Setting up profiles and fan-out caps

Because your fan-out needs differ by hardware tier, set these limits within each specific Hermes profile. The dispatcher reads the `delegation:` block from whichever profile it's assigned to.

**Step 1: Clone your default profile.** Create a new isolated environment tailored for technical work:

```bash
hermes profile create kanban-coding --clone default
```

This generates a directory at `~/.hermes/profiles/kanban-coding/` containing its own `config.yaml`.

**Step 2: Configure model and fan-out per profile.** Open the specific profile's config (e.g. `~/.hermes/profiles/kanban-coding/config.yaml`) and set both the model ID and the concurrency cap.

*Example: R9700 coding profile (strict cap of 2)*

```yaml
# File: ~/.hermes/profiles/kanban-coding/config.yaml
model:
  default: Qwen3.6-27B-Q8-R9700-code

delegation:
  max_concurrent_children: 2   # Strictly matches the R9700 production slot limit
```

*Example: Strix Halo auxiliary profile (higher throughput)* — for web extraction using the MoE model on `ai`:

```yaml
# File: ~/.hermes/profiles/aux-web/config.yaml
model:
  default: Qwen3.6-35B-A3B-Q8-8060S-fast

delegation:
  max_concurrent_children: 4   # Matches the Strix Halo MoE service capacity
```

**Step 3: Assign profiles to your workflow.**

*Global dispatcher* — add this to your main `~/.hermes/config.yaml` to route all Kanban workers through your new capped config:

```yaml
kanban:
  dispatcher_profile: kanban-coding
```

*Per-task execution* — to override it for a single command, use the profile flag:

```bash
hermes kanban --profile aux-web dispatch
```

### Summary of recommendations

1. **Ignore the 9B for speed:** While it's text-only, its ~14 t/s is too slow for aux tasks that fire frequently (like search). It should ideally only be used to offload a specific "low-stakes" task that absolutely cannot fail or hallucinate on a simple fact.
2. **Use MoE models for auxiliary everything:** The Strix Halo hardware (`ai` box) is tuned for these, making them the fastest options in your entire fleet.
3. **Think less (mostly):** Most auxiliary tasks are "dumb" extractions or formatting jobs. Using `-fast` variants prevents the LLM from wasting time and tokens on reasoning blocks it doesn't need.
4. **Isolate Kanban/coding work:** Use a dedicated `kanban-coding` profile pointing at `Qwen3.6-27B-Q8-R9700-code`. The `-code` suffix handles all sampler tuning automatically (temp 0.6, no presence penalty), and limiting `max_concurrent_children: 2` keeps you within the R9700's slot limits.

---

## Reasoning-loop mitigation

How we stop the self-hosted Qwen models from getting stuck in a "thinking" loop, and exactly what to change in `.hermes/config.yaml` to apply it.

### The problem

The thinking-on Qwen models (`Qwen3.6-*`) occasionally get stuck in a loop *inside* their reasoning trace: they keep emitting reasoning tokens and never emit the end-of-thinking marker. A genuine loop runs to 20K+ tokens, which:

- produces an **empty `content`** with `finish_reason: "length"` (the budget was spent on the runaway trace, leaving nothing for the answer), and
- ties up a GPU slot on the fleet for the whole run.

This is also covered under [Usage notes](#usage-notes-important) and [Etiquette & limits](#etiquette--limits).

### The mitigation: `thinking_budget_tokens`

The endpoint supports a llama.cpp extension, **`thinking_budget_tokens`**. Send it in the request body and the server forces the model to stop thinking after ~N tokens, close the reasoning trace, and produce the answer. Reasoning stays **on** for real work, but a runaway trace can't tie up the slot — the middle ground between full thinking and the thinking-off `-fast` ids.

Rough sizing (from the endpoint docs):

| Task type | Budget |
|---|---|
| Short / tool-calling | ~256 |
| General chat | ~1024 |
| Hard reasoning / coding | ~4096 (a genuine loop runs to 20K+, so 4096 still bounds it) |

> ⚠️ The field is **`thinking_budget_tokens`**. A `reasoning_budget` field (vLLM's name) is silently ignored by this endpoint.
>
> ⚠️ It's a non-standard (llama.cpp) field, so it must be passed through `extra_body` — many SDKs strip unknown top-level params. Hermes forwards `extra_body` verbatim into each chat-completions request.

The `-fast` model ids disable thinking server-side, so they have no reasoning trace to loop on — `thinking_budget_tokens` is a harmless no-op for them.

### How it reaches each Hermes model slot

`extra_body` is wired into requests by two different mechanisms in Hermes:

- **Main agent + fallback** — at agent init, Hermes matches a `custom_providers` entry by **base_url + model** and merges that entry's `extra_body` into the request (`agent/agent_init.py` → `_merge_custom_provider_extra_body`). This is the path that actually reaches the *main* gateway agent. (The gateway drops provider-level `request_overrides`, but this init-time merge is independent of that, so it still applies.) A `custom_providers` entry with **no `model:` field matches any model** on that base_url, which we use as a catch-all.
- **Auxiliary tasks** (vision, compression, …) — each `auxiliary.<task>` slot has its own `extra_body`, forwarded verbatim on every call for that task.

### What to change in `.hermes/config.yaml`

**1. `custom_providers` — main agent, fallback, and all `-code` variants**

```yaml
custom_providers:
- name: Llm.stormes.net
  base_url: https://llm.stormes.net/v1
  api_key: <key>
  model: Qwen3.6-35B-A3B-Q8-8060S          # the default main model
  extra_body:
    thinking_budget_tokens: 4096

# Catch-all: an entry with no `model:` matches ANY model on this base_url.
- name: Llm.stormes.net-thinking-budget
  base_url: https://llm.stormes.net/v1
  api_key: <key>
  extra_body:
    thinking_budget_tokens: 4096
```

The explicit `Qwen3.6-35B-A3B-Q8-8060S` entry wins by exact match for the default main model; the model-less catch-all covers everything else on the endpoint. Net coverage:

| Model | Budget | Matched by |
|---|---|---|
| `Qwen3.6-35B-A3B-Q8-8060S` (main) | 4096 | explicit entry |
| `Qwen3.6-35B-A3B-Q8-780M` (fallback) | 4096 | catch-all |
| `Qwen3.6-35B-A3B-Q8-8060S-code` | 4096 | catch-all |
| `Qwen3.6-35B-A3B-Q8-780M-code` | 4096 | catch-all |
| `Qwen3.6-27B-Q8-R9700-code` (best coder) | 4096 | catch-all |
| `Gemma-4-26B-A4B-Q8-8060S-code` | 4096 | catch-all |
| any `-fast` id | 4096 → no-op | catch-all (thinking off; ignored server-side) |

So switching the main slot or a coding lane to any thinking-on `-code` variant keeps the loop budget automatically.

**2. Thinking-on auxiliary tasks**

Gemma also thinks by default, so the two thinking-on auxiliary slots get a budget too:

```yaml
auxiliary:
  vision:
    model: Gemma-4-26B-A4B-Q8-8060S
    extra_body:
      thinking_budget_tokens: 1024     # OCR/vision is mostly extractive
  compression:
    model: Gemma-4-26B-A4B-Q8-8060S
    extra_body:
      thinking_budget_tokens: 4096     # logic-heavy; keep the budget generous
```

**3. Left unchanged: the `-fast` auxiliary slots**

`web_extract`, `skills_hub`, `approval`, `mcp`, `title_generation`, `triage_specifier`, `kanban_decomposer`, `profile_describer`, `curator`, and the `delegation` worker all use `-fast` (thinking-off) ids. They can't loop in a reasoning trace, so they need no budget.

### Tuning notes

- **Want faster, tighter agent turns?** Lower the main `thinking_budget_tokens` toward ~1024. The agent does a lot of tool-calling, where deep reasoning is rarely needed; 4096 is the safe coding default that won't clip legitimate reasoning.
- **Still seeing empty answers with `finish_reason: "length"`?** The overall `max_tokens` must be larger than `thinking_budget_tokens` so there's room for the answer after the trace closes. Keep `max_tokens` ≥ 512.
- **Want zero reasoning for a slot?** Use a `-fast` model id instead of a budget — it disables thinking entirely server-side.

---

## Benchmarks

Measured 2026-05-31, identical harness across all models: live endpoint, sampler `temp 0.7 / top-p 0.9`, 120-token decode for solo, 200-token decode for concurrency, single warm sample (±5% noise). "Decode" = tokens/sec generated; "prefill" = tokens/sec your prompt is read at.

### Solo decode (tokens/sec)

| Model | short (~16 tok) | medium (~2K tok) | long (~5K tok) | vision |
|---|---|---|---|---|
| `Qwen3.6-35B-A3B-Q8-8060S` | **53.7** | **53.0** | **52.2** | **53.6** |
| `Gemma-4-26B-A4B-Q8-8060S` | 47.1 | 43.5 | 40.8 | 46.6 |
| `Qwen3.6-27B-Q8-R9700` | 30.7 | 34.1 | 33.3 | 32.3 |
| `Qwen3.6-35B-A3B-Q8-780M` | 19.9 | 19.7 | 19.5 | 19.8 |
| `Qwen3.5-9B-Q4-780M` | 14.3 | 14.2 | 14.0 | — |

### Solo prefill (tokens/sec — how fast your prompt is ingested)

| Model | medium (~2K tok) | long (~5K tok) |
|---|---|---|
| `Gemma-4-26B-A4B-Q8-8060S` | **1396** | **1250** |
| `Qwen3.6-35B-A3B-Q8-8060S` | 970 | 990 |
| `Qwen3.6-27B-Q8-R9700` | 601 | 792 |
| `Qwen3.6-35B-A3B-Q8-780M` | 321 | 324 |
| `Qwen3.5-9B-Q4-780M` | 233 | 227 |

### Concurrency — aggregate decode (tokens/sec across N simultaneous requests)

| Model | N=1 | N=2 | N=4 |
|---|---|---|---|
| `Qwen3.6-35B-A3B-Q8-8060S` | 53.3 | 77.7 | **106.4** |
| `Gemma-4-26B-A4B-Q8-8060S` | 46.9 | 73.4 | 103.2 |
| `Qwen3.6-35B-A3B-Q8-780M` | 19.8 | 26.6 | 32.5 |
| `Qwen3.6-27B-Q8-R9700` | 30.2 | 36.5 | — (2-slot max) |
| `Qwen3.5-9B-Q4-780M` | 14.3 | — (1 slot) | — |

**Takeaways:** the `8060S` Strix Halo box is the fastest tier (~53 t/s, scales to ~106 t/s aggregate under load). Gemma is close and ingests long prompts the fastest. The dual-GPU `R9700` runs a dense model at ~31–34 t/s with the best quality-per-token but lighter concurrency. The `780M` nodes are the half-speed overflow/lightweight tier.

---

## Usage notes (important)

- **Budget `max_tokens` generously — at least 300, ideally 512+.** The Qwen 3.6 and Gemma 4 models "think" before answering: they emit a reasoning trace into `reasoning_content` first, then the answer into `content`. If your `max_tokens` is too small, the cap can be spent on the reasoning trace and you'll get an **empty `content`** with `finish_reason: "length"`. Give it room.
- **If a model "thinks" forever and never answers (empty `content`, `finish_reason: "length"` even with a big `max_tokens`), cap the reasoning phase with `thinking_budget_tokens`.** The Qwen models occasionally get stuck in a loop *inside* their reasoning trace and never emit the end-of-thinking marker. Send `"thinking_budget_tokens": N` and the server forces the model to stop thinking after ~N tokens, close the trace, and produce the answer:
  ```json
  {
    "model": "Qwen3.6-35B-A3B-Q8-8060S",
    "messages": [ ... ],
    "max_tokens": 1024,
    "thinking_budget_tokens": 256
  }
  ```
  Rough sizing: **~256** for short / tool-calling tasks, **~1024** for general chat, **~4096** for hard reasoning / coding (a genuine loop runs to 20K+ tokens, so even 4096 bounds it). This is the middle ground — reasoning stays *on* but can't run away — between full thinking and the `-fast` (thinking-off) ids. The field is a llama.cpp extension, so pass it via your SDK's `extra_body` if it strips non-standard params. ⚠️ The field is **`thinking_budget_tokens`** — a `reasoning_budget` field (vLLM's name) is silently ignored by this endpoint. See [Reasoning-loop mitigation](#reasoning-loop-mitigation) for the Hermes config that applies this fleet-wide.
- **Vision:** send OpenAI-style multimodal content to any model marked ✓. Base64 data URIs work:
  ```json
  {
    "model": "Gemma-4-26B-A4B-Q8-8060S",
    "messages": [{"role": "user", "content": [
      {"type": "text", "text": "What's in this image?"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ..."}}
    ]}],
    "max_tokens": 512
  }
  ```
- **Streaming:** add `"stream": true` for token-by-token SSE.
- **Gemma also thinks by default** (just like the Qwen models — it emits a `reasoning_content` trace first). For direct answers with no reasoning, use the **`Gemma-4-26B-A4B-Q8-8060S-fast`** model id, or send `"chat_template_kwargs": {"enable_thinking": false}`. (Top-level `"enable_thinking"` is ignored.)
- **Turning thinking OFF on the Qwen models** (for fast / tool-calling agents that don't need a reasoning trace) — the **only** working form is a nested `chat_template_kwargs`:
  ```json
  {
    "model": "Qwen3.6-35B-A3B-Q8-8060S",
    "messages": [ ... ],
    "chat_template_kwargs": { "enable_thinking": false }
  }
  ```
  It **must** be nested inside `chat_template_kwargs`. A top-level `"enable_thinking": false` is silently ignored, and the old `/no_think` prompt trick no longer works on Qwen 3.6. ⚠️ Many high-level clients/SDKs won't forward this nested field (it isn't a standard OpenAI param). **Easiest path: just use the `-fast` model id** (e.g. `Qwen3.6-35B-A3B-Q8-8060S-fast`) — it disables thinking server-side, so any client gets no-reasoning output with zero special config. See [Every callable model id](#every-callable-model-id).
- **Sampler:** each model is launched with its author-recommended sampler baked in, so you **usually don't need to set anything** — a request with just `messages` + `max_tokens` is fine. Override per request only for a task-specific profile (e.g. coding). See [Suggested sampler settings](#suggested-sampler-settings-model-card-defaults) below.
- **Model id must match exactly** (case-sensitive) one of the ids from `GET /v1/models`, or you'll get a 404 listing the available models.

---

## Suggested sampler settings (model-card defaults)

Each model already runs with these author-recommended values as the **server default**, so for normal use you can send just `messages` + `max_tokens` and ignore this table. Set these explicitly only if (a) your client overrides sampler values, or (b) you want a task-specific profile such as coding.

| Model | Mode | `temperature` | `top_p` | `top_k` | `min_p` | `presence_penalty` |
|---|---|---|---|---|---|---|
| **Qwen 3.6** (`...35B-A3B...`, `Qwen3.6-27B-Q8-R9700`) | thinking / general *(default)* | 1.0 | 0.95 | 20 | 0.0 | 1.5 |
| **Qwen 3.6** | coding / precise | **0.6** | 0.95 | 20 | 0.0 | **0.0** |
| **Gemma 4** (`Gemma-4-26B-A4B-Q8-8060S`) | general *(thinking on by default)* | 1.0 | 0.95 | 64 | — | — |
| **Qwen 3.5 9B** (`Qwen3.5-9B-Q4-780M`) | general | 1.0 | 0.95 | 20 | 0.0 | 1.5 |

**Notes for agent builders:**

- **Coding / agentic work on the Qwen models:** drop `temperature` to **0.6** and `presence_penalty` to **0** for more deterministic, less "creative" output. This is the single most useful override.
- **Gemma is different on purpose** — it wants a wider `top_k` (64) and **no** `min_p` / penalties. Don't copy Qwen's `presence_penalty` onto it; that's not what its model card recommends.
- **`max_tokens`:** keep it ≥ 300 (ideally 512+) on every Qwen 3.6 / Gemma 4 call so the thinking trace doesn't eat the budget — see [usage notes](#usage-notes-important).
- **Field names & SDK quirks:** `temperature`, `top_p`, `presence_penalty` are standard OpenAI fields. `top_k`, `min_p`, and `repetition_penalty` are **llama.cpp extensions** — most OpenAI SDKs only send them if you pass them through an `extra_body` (Python) / extra-params mechanism. If your client can't send them, the server's baked-in defaults still apply, so you lose nothing.
- **Don't confuse** `presence_penalty` (what these models use) with `frequency_penalty` (different math). Send `presence_penalty`.

> TL;DR for an agent config: point at the base URL, pick a model, set `max_tokens: 512`, and leave the sampler alone — unless it's a coding agent, in which case set `temperature: 0.6`.

---

## How it's served (the stack)

Four small nodes on a home LAN, all running llama.cpp, merged behind one URL:

| Node | Hardware | Serves |
|---|---|---|
| **crypto1** | Dell Precision 5820, **2× AMD Radeon AI PRO R9700** (32 GB each, RDNA 4) | `Qwen3.6-27B-Q8-R9700` (dense 27B, dual-GPU layer-split, speculative decoding) |
| **ai** | Ryzen AI MAX+ 395, **Radeon 8060S** iGPU (Strix Halo, 128 GB unified) | `Qwen3.6-35B-A3B-Q8-8060S` + `Gemma-4-26B-A4B-Q8-8060S` (share the GPU) |
| **ai4** | Ryzen 9 7940HS, **Radeon 780M** iGPU (Phoenix, 64 GB) | `Qwen3.6-35B-A3B-Q8-780M` |
| **ai3** | Ryzen 7 + **Radeon 780M** iGPU (Phoenix, 16 GB) | `Qwen3.5-9B-Q4-780M` |

A lightweight router merges all nodes into a single `/v1` surface and dispatches each request by its `model` field. A Caddy reverse proxy in front terminates TLS (Let's Encrypt) and enforces bearer-token auth. Everything is **OpenAI-compatible**, so any tool that speaks the OpenAI API works unchanged — just change the base URL and key.

---

## Etiquette & limits

This is a **home rig shared on a single key** — no per-user quotas are enforced, so a little courtesy keeps it pleasant for everyone:

- **Cap `max_tokens`** to what you actually need (but ≥ 300 — see [usage notes](#usage-notes-important)). Don't leave it unbounded on a loop. If a model gets stuck "thinking," add `thinking_budget_tokens` (see [Reasoning-loop mitigation](#reasoning-loop-mitigation)) so a runaway reasoning trace can't tie up a GPU slot.
- **Go easy on huge fan-outs.** The fast box handles ~4 parallel requests well; dozens of simultaneous requests will queue and slow everyone down.
- **Prefer the right tier:** push bulk/low-stakes text to `Qwen3.5-9B-Q4-780M` or the `780M` Qwen rather than hammering the fast `8060S` box.
- **Don't share your key** or commit it to a repo. If it leaks, tell the owner and they'll rotate it.
- If something's down or slow, ping the owner — these are real machines that occasionally get rebooted or retuned.
