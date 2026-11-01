
# ⚡ HTTP CLI Benchmarker

A fast, lightweight, and asynchronous HTTP stress-testing CLI built with Python (`asyncio`, `aiohttp`) and `rich`. Designed for developers who need real-time latency metrics and throughput profiling directly in the terminal.

<img width="1109" height="503" alt="Capture d&#39;écran 2026-11-01 174251" src="https://github.com/user-attachments/assets/1cec1915-3578-4edc-9e36-d0ff5792929e" />


---

## ✨ Key Features

* **High Concurrency:** Powered by `asyncio` and `aiohttp` for non-blocking, high-throughput load generation.
* **Rich Terminal UI (TUI):** Real-time progress tracking, live RPS counters, and clean latency summaries.
* **Detailed Metrics:** Calculates percentiles ($p50$, $p95$, $p99$), min/mean/max latency, and standard deviation ($stdev$).
* **Flexible Execution:** Supports total request counts (`-n`), duration-based testing (`-d`), and rate-limiting (`--rps`).
* **Headless/CI Mode:** Silent flag (`-q`) tailored for CI/CD automation pipelines.

---

## 🚀 Quick Start

### Prerequisites

Ensure you have Python 3.8+ installed, then install the required dependencies:

```bash
pip install aiohttp rich
📖 Usage
Run 10,000 requests with 200 concurrent workers
Bash
python httpbench.py [https://example.com](https://example.com) -n 10000 -c 200
60-second stress test capped at 3,000 req/s
Bash
python httpbench.py [https://api.example.com/items](https://api.example.com/items) -c 500 -d 60 --rps 3000
POST request with JSON payload & export report to JSON
Bash
python httpbench.py [https://api.example.com/login](https://api.example.com/login) -m POST \
  -H "Content-Type: application/json" -b '{"user":"a","pass":"b"}' \
  -c 100 -n 5000 --json report.json
Read payload from file in headless/quiet mode (ideal for CI/CD)
Bash
python httpbench.py [https://api.example.com/upload](https://api.example.com/upload) -m PUT -b @payload.bin -q -n 1000
📊 Terminal Output Preview
Plaintext
━━━━━━━━━━━━━━━━━━━━━━━━━━━ httpbench → [https://example.com](https://example.com) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
       Progress ████████████████████████████████ 100.0% 10,000/10,000 req
     Requests/s 304  (average 4,305)
Success / Errors 10,000 / 0
Latency p50/95/99 32.4 ms / 36.7 ms / 40.1 ms
     HTTP codes 200: 10,000
────────────────────────────────────── Results ──────────────────────────────────────
       Requests 10,000  (success 10,000, errors 0)
       Duration 2.24 s
Average throughput 4,458.4 req/s
  Data received 5.77 MB
    Latency min 12.2 ms
   Latency mean 43.4 ms  (stdev 67.9 ms)
    Latency p50 33.3 ms
    Latency p90 37.0 ms
    Latency p95 38.8 ms
    Latency p99 530.3 ms
    Latency max 571.5 ms

HTTP status codes
Code  Occurrences
200   10,000
🛠️ Tech Stack
Language: Python

Networking: aiohttp / asyncio

Interface: rich

🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the [suspicious link removed].

Fork the Project

Create your Feature Branch (git checkout -b feat/AmazingFeature)

Commit your Changes (git commit -m 'feat: Add some AmazingFeature')

Push to the Branch (git push origin feat/AmazingFeature)

Open a Pull Request

📜 License
Distributed under the MIT License. See LICENSE for details.
