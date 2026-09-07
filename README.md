# Local AI Agent

Installed and tested on 7 September 2026. Use the **Start Local AI Agent** desktop shortcut to open the standalone **Local Agent — LUXE** Windows app. The selected connection profile is **LOCAL AGENT**. The browser URL **http://127.0.0.1:8000/** remains available as an alternative. See `desktop/README.md` for the app and calm cream theme.

## Installed stack

| Component | Installed version / address |
|---|---|
| SillyTavern | Official stable 1.18.0; http://127.0.0.1:8000 |
| Model | Unsloth GGUF conversion of Qwen3.5-4B, 4 billion parameters, Q6_K |
| Inference | Official llama.cpp Windows CUDA 12.4 build b10839, commit 0cae43063; http://127.0.0.1:5001/v1 |
| Search | Official SearXNG source, commit 3e454637fb9829756c805dd9c02100f0bc9520fd; http://127.0.0.1:8080 |
| Web integration | Official SillyTavern Extension-WebSearch, with small local compatibility, citation and content-limit patches |
| Runtime | Project Python 3.12.14 environment with Waitress; existing Node 26.3.1 |

SillyTavern sends chat to llama.cpp. Its Web Search extension queries local SearXNG, visits public result pages through SillyTavern, extracts text into an attachment, and supplies snippets, source URLs and page text to Qwen. No paid API is needed. All three listeners bind to **127.0.0.1**. Search queries and webpage requests necessarily go to public services; inference and chat storage remain local.

## Hardware and performance

Ryzen 7 5800H, 8 cores / 16 threads; 16 GB physical RAM (about 13.9 GB usable); RTX 3060 Laptop GPU with 6 GB VRAM, NVIDIA driver 581.80. A compact modern Qwen model preserves headroom with the other applications already open.

The model uses all available GPU layers, a 16,384-token context, one concurrent generation, six CPU threads, Flash Attention and Q8 KV cache. RAM prompt caching is disabled. Explicit loading without mmap plus `--no-host` reduced resident RAM substantially on this machine. Tests left approximately 4 GB physical RAM and 2 GB VRAM free. Windows commit usage is relatively high with the user's other applications open; see the recorded measurements in `logs/lifecycle-tests.json`. Short direct responses measured around 50 tokens/second; speed varies with prompt length and other GPU activity.

Model file: `models/Qwen3.5-4B-Q6_K.gguf`, 3,525,956,768 bytes. SHA-256 verified against Hugging Face metadata:

`fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66`

## Start, stop and status

Run in PowerShell from `C:\Users\Never\Desktop\UC-LLM`:

```powershell
.\start.ps1 -OpenApp
.\stop.ps1
.\restart.ps1 -OpenApp
.\status.ps1
```

Start waits for all services and checks live search. Repeated starts reuse existing project processes. Stop verifies both creation time and executable path before terminating a process. It does not stop unrelated Python, Node or AI processes. Startup refuses an occupied port before launching anything; it never kills the competing service.

The desktop shortcut launches `desktop/Local Agent.exe`, which starts the services without a console window and opens the local chat in its own WebView2 window. The launcher supplies a process-only script execution policy; the machine's execution policy, firewall and antivirus were not changed. Services are started on demand, not automatically at Windows sign-in. Closing the app window leaves the services available; use `stop.ps1` to free their resources.

## Web research

Enabled engines: Google, Bing, Brave, DuckDuckGo, Wikipedia, GitHub and Stack Overflow. During tests Google, Bing and Brave supplied results. DuckDuckGo returned a CAPTCHA; the other engines continued. Engine availability can change.

Automatic search uses English/Danish current-information triggers, such as “latest”, “current”, “news”, “price”, “version”, “seneste”, “nyheder” and “søg”. You can explicitly say **Search for …** or enclose a precise query in single backticks. Stable questions do not normally trigger search. A leading `!` discards earlier search triggers; a leading period prevents the current message from creating a new query. The native extension can retain previous research for follow-up questions.

Defaults: eight source snippets, three visited pages, 6,500 characters per page, 6,500 characters of search context, five-minute query cache. This is **one native search pass per matching message**, not an autonomous multi-iteration agent. `MAX_SEARCH_ITERATIONS` is therefore 1. It uses deterministic triggers rather than unreliable model tool calls. Additional research can be requested in a follow-up.

Page extraction removes scripts, navigation, headers, footers, forms and sidebars, then retains paragraphs, headings, lists and table cells. Retrieval has a 15-second timeout and a 4 MB response limit. JavaScript-only pages, paywalls and bot checks can still prevent reading; the model may then have only snippets or other pages. Retrieved text is explicitly marked untrusted. The installed system prompt forbids following webpage instructions or inventing citations; this is a language-model instruction, not a guarantee that every answer is correct. The agent has no shell or private-file browsing tools.

Search failure is reported to the model with an instruction to acknowledge failed live verification. Local conversation remains available. Optional Tavily was skipped because no environment key was present.

## Configuration and model switching

Central settings are in `config.json`. The model and port values are used by the launcher. Search settings are installed into the LOCAL AGENT profile by `setup_frontend.py`. `.env` and `.env.example` are provided for future optional credentials and `.env` is ignored; no key is required or currently configured. Adding a key alone does not enable a paid provider.

To switch models or ports, close the browser tab and stop the stack, place a compatible GGUF in `models`, edit `MODEL_PATH`, `MODEL_NAME` and other desired values in `config.json`, then run:

```powershell
.\runtime\python\Scripts\python.exe .\setup_frontend.py
.\runtime\python\Scripts\python.exe .\patch_extensions.py
.\start.ps1 -OpenBrowser
```

`setup_frontend.py` intentionally reinstalls the managed LOCAL AGENT connection, prompt and research defaults. Back up `apps\SillyTavern\data\default-user\settings.json` first if you have customized those settings. Custom models must support llama.cpp chat templates; the current Qwen profile uses strict message processing. Images/vision were not configured.

## Updates

```powershell
.\update.ps1
# Or update only one component:
.\update.ps1 -Component SillyTavern
.\update.ps1 -Component SearXNG
.\update.ps1 -Component Inference
```

The updater stops this stack, backs up source/configuration under `runtime\backups`, retrieves official releases/source, reinstalls required dependencies, reapplies local compatibility patches, starts services and runs integration tests. **It never replaces the model.** SillyTavern uses its latest stable release. llama.cpp uses published Windows CUDA builds; their version string can include `dev` because the project publishes rolling builds. SearXNG likewise publishes rolling production source rather than numbered stable releases. New versions may require compatibility work; the updater reports failures and preserves backups. Its syntax and component commands were checked, but a future-version upgrade cannot be tested in advance.

## Switching between Codex and GitHub Copilot

The Git repository is the source of truth for code. The installed copy at
`C:\Users\Never\Desktop\UC-LLM` is a runtime installation and contains local models,
dependencies, chats and logs that must not be copied into Git.

After editing the installed copy directly with Codex, import only the supported source
files into the current checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-desktop.ps1 -Direction FromDesktop
git diff
git add .
git commit
```

After pulling or changing code in GitHub Copilot, deploy the source files back to the
installed copy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-desktop.ps1 -Direction ToDesktop
.\desktop\build.ps1
```

Check both locations without changing anything:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\sync-desktop.ps1 -Direction Status
```

The sync list excludes `apps`, `models`, `runtime`, `logs`, `downloads`, `.env` and all
chat/database data. It compares text files with normalized line endings, so Windows
newline differences do not appear as false changes.

The Web Search extension's independent auto-update is disabled so it cannot silently remove the local content-limit patches; update it using the project updater. Windows adaptations are in `configure.py`; frontend patches are in `patch_extensions.py`.

## Tests and evidence

```powershell
.\runtime\python\Scripts\python.exe .\test_stack.py
.\test-lifecycle.ps1
```

The first checks direct generation, real SillyTavern API generation, live SearXNG JSON and HTML integration, actual page retrieval, sourced synthesis, offline arithmetic and simulated unavailable search. The second stops/restarts the stack, tests an occupied port without killing its listener, checks duplicate prevention and records memory. It interrupts active local chats, so run it when no generation is in progress.

Evidence: `logs/test-results.json`, `logs/lifecycle-tests.json`, `logs/hardware.json`, and the browser-verified research chat. The browser test searched the web, attached extracted content and answered Python **3.14.7** with the returned Python.org URLs. An offline Danish chat was also generated in the browser.

## Locations and troubleshooting

Everything created for the stack is in `C:\Users\Never\Desktop\UC-LLM`, except the desktop shortcut. Models are in `models`; applications in `apps`; process identity records, the virtual environment and search configuration in `runtime`; logs in `logs`. SillyTavern chats and preferences are in `apps\SillyTavern\data\default-user`.

- No response: run `status.ps1`, then inspect `logs/llm.err.log` and `logs/sillytavern.err.log`.
- Search error: inspect `logs/searxng.err.log`; retry later or use an explicit shorter query. One engine failing does not mean all search is down.
- Port occupied: select a free port in `config.json` and reinstall the managed profile as above. Startup will not stop the competing application.
- Memory pressure: close unneeded applications or select a smaller quantization/model. Do not increase context or concurrency blindly on this 6 GB GPU.
- Python is self-contained: `runtime/base-python` contains the base interpreter and standard library; `runtime/python` contains this project's isolated dependencies. Removing Codex's runtime cache will not remove this installation. Keep the project at its installed location; moving it requires recreating the virtual environment and updating the desktop shortcut.

Official sources: [SillyTavern](https://github.com/SillyTavern/SillyTavern/releases/tag/1.18.0), [Web Search extension](https://github.com/SillyTavern/Extension-WebSearch), [llama.cpp build](https://github.com/ggml-org/llama.cpp/releases/tag/b10839), [SearXNG](https://github.com/searxng/searxng), [model download](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF).

## Milestone One local tools

`local_tools.py` is the local-only Tool Router behind the Files area and
`file_registry_server.py`. It provides structured `FILE_SEARCH`,
`FILE_INSPECT`, copy/move/rename/delete, folder creation, duplicate and disk
analysis, document/PDF/TXT/Markdown/CSV handling, real XLSX read/create, WAV
metadata/analysis/compare, and `MULTI_TOOL_TASK`. Every run is validated,
permission-checked, verified, and persisted in the existing SQLite file
registry (`tool_runs`, `file_operations`, `indexed_files`, and audio cache
tables are additive migrations).

The HTTP bridge remains loopback-only:

* `GET /files` — library and indexed-file results
* `GET /tools` — structured tool catalog
* `POST /tools/run` — `{ "tool": "...", "arguments": {...}, "approved": true }`
* `POST /index/refresh` — refresh explicitly supplied roots
* `GET /operations` — recent operation history

Indexing is incremental and only scans roots explicitly supplied by the user
or application. Destructive actions require approval; overwrite and permanent
delete require explicit approval. Normal delete uses the Windows Recycle Bin
when `send2trash` is installed, otherwise a `.localai-trash` quarantine is
used. No shell, PowerShell, macro, cloud upload, or embedded-document execution
is exposed. `openpyxl` enables XLSX support; DOCX/PDF text support is local and
dependency-free. Audio analysis is complete for WAV; MP3/FLAC/AIFF/M4A/OGG
metadata requires optional `mutagen`, and true peak/key/BPM are reported as
unavailable rather than fabricated.

Generated files default to `runtime/file-library/generated` and are registered
in Files with their tool run. Run the focused subsystem checks with:

```powershell
python -m unittest -v test_file_registry.py test_local_tools.py
```
