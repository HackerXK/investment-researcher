# Hardware Requirements & Setup

## Infrastructure Overview

The platform runs on a **workstation-first architecture**. All compute and storage live on the AMD workstation during Phases 0–4. Additional tiers are added only when triggered by capacity thresholds:

1. **AMD Workstation** — sole compute host + storage (Docker services, GPU inference via RTX 5090, 6TB NVMe across 2 volumes: 2TB P41 + 4TB SN5000 RAID 0) — **already purchased, active from Phase 0**
2. **NAS** — bulk archival storage (RAID array, file serving, backups) — **deferred to Phase 5** (triggered when NVMe storage approaches 70% total capacity ~4.2TB)
3. **Mac Studio Cluster** — future expansion for very large models (405B+) and inference monetization — **deferred to Phase 6+**

The AMD workstation fundamentally changes the economics of this project. With a Ryzen 9 9950X3D, 64 GB DDR5, and an RTX 5090 (32 GB VRAM), it serves as both the Docker host for all platform services AND the primary LLM inference engine for models up to ~30B (fully in VRAM) or ~70B (with partial CPU offload). Its 6TB NVMe — configured as 2 volumes (2TB P41 standalone + 4TB WD SN5000 RAID 0 stripe) — holds all data with generous headroom, though the RAID 0 array has no redundancy, making the NAS backup target important once provisioned.

### Phases 0–4 Topology (No NAS)

```
┌────────────────────────────────────────────────────────────────────┐
│                           HOME NETWORK                             │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │     AMD Workstation (Windows 11 + WSL2) — ALREADY OWNED     │  │
│  │                                                              │  │
│  │  CPU: Ryzen 9 9950X3D (16c/32t)                             │  │
│  │  RAM: 64 GB DDR5-6000                                       │  │
│  │  GPU: RTX 5090 32 GB VRAM                                   │  │
│  │  SSD: 6 TB NVMe — 2 volumes (2TB P41 + 4TB SN5000 RAID 0)   │  │
│  │  PSU: 1200W                                                 │  │
│  │                                                              │  │
│  │  Docker Containers (WSL2):                                   │  │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐      │  │
│  │  │ FalkorDB │ │ Langfuse  │ │Ingestion │ │ Agent     │      │  │
│  │  │ (16-32GB)│ │ +Postgres │ │ Worker   │ │ Runner    │      │  │
│  │  └──────────┘ └───────────┘ └──────────┘ └───────────┘      │  │
│  │                                                              │  │
│  │  LLM Inference (GPU):                                       │  │
│  │  ┌──────────────────────────┐   Data: ./data/               │  │
│  │  │ vLLM / llama.cpp (CUDA)  │   ├── falkordb/              │  │
│  │  │ RTX 5090 — 32 GB VRAM   │   ├── postgres/              │  │
│  │  │ OpenAI-compatible API    │   ├── duckdb/                │  │
│  │  │ http://localhost:8000    │   ├── sqlite/                │  │
│  │  └──────────────────────────┘   ├── raw/                   │  │
│  │                                  └── uploads/              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌────────────────────────┐                                       │
│  │  Developer Machine     │                                       │
│  │  (MacBook Pro M2 Pro   │                                       │
│  │   — CLI + SSH only)    │                                       │
│  └────────────────────────┘                                       │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │            FUTURE (Phase 5+, if NVMe hits 70%)               │  │
│  │                                                              │  │
│  │  ┌────────────────────────┐                                  │  │
│  │  │     10-Bay NAS         │  SMB shares to workstation      │  │
│  │  │   (Storage Only)       │  Archive data, model weights,   │  │
│  │  │   128–256 TB RAID 6    │  backups                        │  │
│  │  └────────────────────────┘                                  │  │
│  │                                                              │  │
│  │            FUTURE (Phase 6+, if validated)                   │  │
│  │                                                              │  │
│  │  ┌──────────────┐  TB5/RDMA  ┌──────────────┐               │  │
│  │  │ Mac Studio 1 │◄──────────►│ Mac Studio 2 │               │  │
│  │  │ 512 GB       │            │ 512 GB       │               │  │
│  │  └──────────────┘            └──────────────┘               │  │
│  │  For: 405B models, inference monetization                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## Tier 1: AMD Workstation (Compute Host + GPU Inference) — ALREADY PURCHASED

This machine is the platform's workhorse. It runs all Docker containers (FalkorDB, Langfuse, ingestion, agents), stores all data across 2 NVMe volumes (6TB total: 2TB P41 + 4TB SN5000 RAID 0), AND serves as the primary LLM inference engine via the RTX 5090. **This machine is already purchased and built**, making it the zero-additional-cost compute foundation.

> **Note**: The workstation runs Windows 11 Pro + WSL2. All Docker containers and CLI commands run inside WSL2. See [OS Considerations](#os-considerations) below.

See [06-deployment.md](06-deployment.md) for docker-compose.yml, bind mount paths, and NAS migration steps.

### Hardware Specification

| Component | Specification | Notes |
|-----------|--------------|-------|
| **CPU** | AMD Ryzen 9 9950X3D (16 cores / 32 threads) | Top-tier desktop CPU. 3D V-Cache = excellent per-core performance. Handles all Docker workloads comfortably |
| **RAM** | 64 GB DDR5-6000 CL30 (Corsair, 2×32 GB) | Sufficient for FalkorDB (16–32 GB) + all containers + system. Allows partial CPU offload for models slightly >32 GB |
| **GPU** | Gigabyte RTX 5090 Windforce 32 GB VRAM | Blackwell architecture, CUDA. Primary inference engine for ≤30B models (fully in VRAM) and ≤70B models (with partial CPU offload) |
| **SSD (primary)** | SK Hynix Platinum P41 2 TB NVMe Gen4 | Fastest drive (Gen4). Hosts `./data/falkordb/`, `./data/postgres/`, `./data/duckdb/`, `./data/sqlite/` — latency-sensitive databases |
| **SSD (secondary × 2)** | WD Blue SN5000 2 TB NVMe × 2 → **RAID 0 = 4 TB volume** | Striped for full 4TB capacity. Hosts raw data, uploads, model weights, and cache. RAID 0 = no redundancy — NAS backup is critical |
| **Total NVMe** | **6 TB across 2 logical volumes** (2TB + 4TB RAID 0) | |
| **PSU** | Lian Li Edge Gold 1200W | Ample headroom for CPU + RTX 5090 under full load |
| **Cooler** | Lian Li GA II Trinity N Performance 360mm AIO | Adequate for sustained 9950X3D workloads |
| **Motherboard** | Gigabyte X870E Aorus Elite WiFi ICE | AM5 socket, PCIe 5.0 x16 for GPU, multiple M.2 slots for future SSD expansion |
| **Case** | Lian Li Lancool 237 TG ATX White | Good airflow for sustained GPU inference |
| **OS** | Windows 11 Pro | Docker Desktop via WSL2. All platform services run inside WSL2; CUDA works natively on Windows via Docker Desktop's WSL2 backend |

> **Receipt total**: ~$3,764 (including $199.99 build service). This machine replaces the need for Mac Studios during Phases 0–5, saving $16,000–40,000 in deferred purchases.

### Docker Services on Workstation

All platform services run as Docker containers on this machine:

| Container | CPU Cores | RAM | Storage | Notes |
|-----------|-----------|-----|---------|-------|
| **FalkorDB** | 2–4 | 16–32 GB | Local NVMe (`/data`) | In-memory graph. **This is why 64 GB system RAM matters** — FalkorDB gets 16–32 GB, leaving 32–48 GB for everything else |
| **Langfuse** | 1–2 | 2–4 GB | — | Observability UI |
| **Langfuse Postgres** | 1–2 | 2–4 GB | Local NVMe | Trace storage |
| **Ingestion Worker** | 2–4 | 2–4 GB | Local NVMe (`./data/edgar/`, `./data/raw/`) | Reads from edgartools local storage and raw files, writes to FalkorDB |
| **Agent Runner** | 2–4 | 2–4 GB | — | Calls local LLM API on same machine |
| **LLM Server** | 2–4 (+ GPU) | 2–4 GB + 32 GB VRAM | Local NVMe (model files) | vLLM or llama.cpp with CUDA backend |
| **Total** | 10–20 of 32 threads | ~40–56 GB | | Leaves headroom for OS and burst workloads |

> **RAM allocation note**: With 64 GB total, running FalkorDB at 32 GB max memory leaves tight headroom. For Phase 0–3 (smaller graph), set `--maxmemory 16g` for FalkorDB. If the graph outgrows 32 GB, consider upgrading to 128 GB DDR5 (the X870E board supports it — 2 additional DIMM slots available, or replace with 4×32 GB).

### Local Storage Layout (Workstation NVMe)

```
# 2 NVMe volumes — allocated by access pattern (paths inside WSL2):
#
# Volume 1: SK Hynix P41 2TB Gen4 (standalone) — fastest, latency-sensitive databases
investment-researcher/
├── data/
│   ├── falkordb/                # FalkorDB RDB persistence (bind mount target)
│   ├── postgres/                # Langfuse Postgres data (bind mount target)
│   ├── duckdb/                  # DuckDB financial time series
│   └── sqlite/                  # reports.db, ingestion.db
#
# Volume 2: WD Blue SN5000 2×2TB RAID 0 = 4TB stripe — sequential/bulk access
├── data/
│   ├── edgar/                   # edgartools local storage (~24 GB metadata + 50–150 GB/year filings)
│   │   ├── reference/           #   ~50 MB — SIC codes, exchanges, tickers
│   │   ├── companyfacts/        #   ~2 GB — XBRL financial facts
│   │   ├── submissions/         #   ~5 GB — company metadata & filing indexes
│   │   └── filings/             #   ~50–150 GB/year — actual filing documents
│   ├── raw/                     # Non-SEC raw data: PDFs, CSVs, news articles
│   └── uploads/                 # User-uploaded documents
├── cache/                       # Temporary processing cache
└── models/
    ├── qwen2.5-32b-q8.gguf     # ~34 GB — fits fully in 32 GB VRAM
    ├── llama-3.1-8b-q8.gguf    # ~9 GB — fits easily
    └── nomic-embed-text.gguf   # ~250 MB
#
# NOTE: RAID 0 = no redundancy. A single SN5000 failure loses the entire 4TB volume.
# Prioritise NAS deployment as a backup target once Phase 5 is triggered.

# Phase 5+ (when NAS is added via SMB mount in WSL2):
# /mnt/nas/archive/              # Bulk archival data offloaded from NVMe
# /mnt/nas/models/               # Full model library
# /mnt/nas/backups/              # Backup target for ./data/ rsync
```

### GPU Inference: Model Capacity Analysis (RTX 5090)

The RTX 5090's 32 GB VRAM determines which models run fully on GPU (fast) vs. requiring CPU offload (slower):

#### Fully in VRAM (Maximum Speed)

| Model | Parameters | Quantization | VRAM Required | Estimated tok/s | Notes |
|-------|-----------|-------------|---------------|-----------------|-------|
| Llama 3.1 8B | 8B | Q8_0 | ~9 GB | 100–150 | Excellent for light agents, triage, classification |
| Llama 3.1 8B | 8B | FP16 | ~16 GB | 80–120 | Maximum quality for routing agents |
| Qwen 2.5 14B | 14B | Q8_0 | ~15 GB | 60–90 | Good mid-range for NL→Cypher |
| Qwen 2.5 32B | 32B | Q4_K_M | ~20 GB | 30–50 | Strong reasoning at high speed |
| Qwen 2.5 32B | 32B | Q8_0 | ~34 GB | ⚠️ Barely fits | ~1 GB over — may need Q6_K instead |
| Llama 3.3 70B | 70B | Q4_K_M | ~42 GB | ❌ Too large | Does not fit in 32 GB VRAM |

#### With CPU Offload (Partial VRAM + System RAM)

For models larger than 32 GB, llama.cpp can offload some layers to CPU (DDR5-6000). This is slower but functional:

| Model | Parameters | Quantization | Total Size | GPU Layers / CPU Layers | Estimated tok/s | Notes |
|-------|-----------|-------------|------------|------------------------|-----------------|-------|
| Qwen 2.5 32B | 32B | Q8_0 | ~34 GB | 58/2 layers GPU, rest CPU | 25–40 | Slight offload, minimal speed loss |
| Llama 3.3 70B | 70B | Q4_K_M | ~42 GB | ~48/32 layers GPU, rest CPU | 8–15 | Noticeable slowdown but usable for batch processing |
| Llama 3.3 70B | 70B | Q3_K_M | ~34 GB | All GPU | 15–25 | Lower quality but fully in VRAM |
| DeepSeek-R1 70B (distill) | 70B | Q4_K_M | ~42 GB | ~48/32 layers GPU, rest CPU | 8–15 | Strong reasoning, partial offload |

> **Key insight**: The RTX 5090 excels at models ≤32B. At Q4 quantization, Qwen 2.5 32B fits comfortably in 32 GB VRAM and delivers 30–50 tok/s — fast enough for real-time interactive use. For heavy batch workloads (KG construction, bulk analysis), 70B at Q4 with partial offload at 8–15 tok/s is acceptable since latency doesn't matter for background processing. This is **3–5× faster** than Apple Silicon running the same model thanks to CUDA Tensor Cores.

#### Comparison: RTX 5090 vs. Mac Studio M4 Ultra

| Factor | RTX 5090 (32 GB VRAM) | Mac Studio M4 Ultra (512 GB) |
|--------|----------------------|------------------------------|
| **Max model fully in memory** | ~32B Q8 or ~20B FP16 | 405B Q8 or ~300B FP16 |
| **Speed (8B Q8)** | ~100–150 tok/s | ~30–50 tok/s |
| **Speed (70B Q4)** | ~8–15 tok/s (partial offload) | ~10–20 tok/s (fully in memory) |
| **Speed (405B Q4)** | ❌ Cannot run | ~5–10 tok/s |
| **Cost** | ~$2,000 (GPU only) | ~$8,000–10,000 (whole unit) |
| **Power** | ~500 W (GPU alone under load) | ~200–370 W (whole unit) |
| **Ecosystem** | CUDA, vLLM, TensorRT-LLM, llama.cpp | MLX, exo, llama.cpp (Metal) |
| **Multi-model** | Limited by 32 GB VRAM | 512 GB fits many models concurrently |

**Conclusion**: The RTX 5090 is the superior choice for models ≤32B (faster, cheaper). Mac Studios are only justified when you need models >70B at full quality (405B) or concurrent multi-model serving. **Defer Mac Studio purchase until Phase 6+.**

### Recommended Model Strategy (Phases 0–5)

| Workload | Model | Quant | Deployment | tok/s (est.) | Notes |
|----------|-------|-------|-----------|-------------|-------|
| **KG construction** (GraphRAG-SDK) | Qwen 2.5 32B | Q4_K_M | Fully in VRAM | 30–50 | Best quality-per-token that fits in VRAM. Strong instruction following |
| **Complex agents** (Ripple, Synthesizer) | Qwen 2.5 32B | Q4_K_M | Fully in VRAM | 30–50 | Multi-hop reasoning. If insufficient, try 70B Q4 with offload for batch |
| **Light agents** (Triage, Data Monitor) | Llama 3.1 8B | Q8_0 | Fully in VRAM | 100–150 | Routing and classification. Extremely fast |
| **NL→Cypher** (GraphRAG-SDK queries) | Qwen 2.5 14B or 32B | Q4–Q8 | Fully in VRAM | 30–90 | Code generation is strong at 14–32B with Qwen |
| **Embeddings** | nomic-embed-text | FP16 | CPU or GPU | N/A | Lightweight, runs alongside main model |
| **Batch KG construction** (overnight) | Llama 3.3 70B | Q4_K_M | Partial offload | 8–15 | When quality matters more than speed. Run overnight |

> **Model hot-swapping**: Only one large model can occupy the GPU at a time. For interactive use, keep the 32B model loaded. For overnight batch processing, swap to 70B Q4. Use a simple script to switch models via the vLLM/llama.cpp API. Light models (8B) and embeddings can run on CPU concurrently if needed.

### Inference Framework Stack

| Framework | Role | Notes |
|-----------|------|-------|
| **[vLLM](https://github.com/vllm-project/vllm)** | Primary inference server (CUDA) | OpenAI-compatible API, PagedAttention for efficient memory, continuous batching. Best throughput for NVIDIA GPUs |
| **[llama.cpp](https://github.com/ggerganov/llama.cpp)** | Alternative / CPU offload | GGUF format, flexible GPU/CPU layer splitting, `--server` mode for OpenAI-compatible API. Use when partial CPU offload is needed |
| **[TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM)** | Maximum performance (optional) | NVIDIA's optimized engine. Requires model compilation. Worth exploring for production models once stable |
| **[text-generation-webui](https://github.com/oobabooga/text-generation-webui)** | Development/testing | Convenient UI for model testing. Not for production |

**Recommended**: **vLLM** as primary (best throughput with CUDA), **llama.cpp** as fallback (for CPU offload scenarios). Both expose OpenAI-compatible `/v1/chat/completions` endpoints.

### API Endpoint Configuration

```
# vLLM startup on workstation
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4 \
    --host 0.0.0.0 --port 8000 \
    --gpu-memory-utilization 0.90 \
    --max-model-len 16384

# OR llama.cpp server (for GGUF models with CPU offload)
./llama-server \
    -m ./models/llama-3.3-70b-q4_k_m.gguf \
    --host 0.0.0.0 --port 8000 \
    -ngl 48 \     # 48 layers on GPU, rest on CPU
    -c 16384

# Application config (same API shape as OpenAI)
LLM_PRIMARY_MODEL=openai/qwen2.5-32b-instruct
LLM_LIGHT_MODEL=openai/llama-3.1-8b-instruct
LLM_API_BASE=http://localhost:8000/v1
LLM_EMBEDDING_MODEL=nomic-embed-text
LLM_EMBEDDING_API_BASE=http://localhost:8001/v1
```

> **LiteLLM note**: The application layer uses LiteLLM (via GraphRAG-SDK and OpenAI Agents SDK) to abstract the backend. Swapping from `http://localhost:8000/v1` (local vLLM) to `https://api.openai.com/v1` (OpenAI cloud) or `http://mac-studio:52415/v1` (future Mac cluster) requires only changing `LLM_API_BASE`. No code changes needed.

### OS Considerations

| Option | Pros | Cons | Recommendation |
|--------|------|------|---------------|
| **Windows 11 Pro + WSL2** | Already installed. Docker Desktop works. Gaming/daily-driver when not running platform. CUDA works natively. All platform commands run in WSL2 terminal | WSL2 memory management can be finicky. Docker Desktop licensing ($5/mo for commercial). Slight overhead vs. bare-metal Linux | **All phases — this is the primary setup** |
| **Ubuntu 24.04 LTS (dual-boot)** | Native Docker, native CUDA, no overhead, better Docker networking, systemd services | Requires separate boot partition. Can't game and run inference simultaneously | **Optional** — only worth it if WSL2 overhead becomes a measurable problem (unlikely for this workload) |
| **Ubuntu Server (headless)** | Maximum performance. SSH-only. Runs 24⁄7 as a server | No desktop. Need separate machine for daily use | **Phase 6+ only** — if the workstation is eventually repurposed as a headless always-on server |

> **Recommendation**: Windows 11 Pro + WSL2 for all phases. Docker Desktop manages containers cleanly, vLLM runs on the RTX 5090 via native Windows CUDA drivers, and all CLI commands run in the WSL2 terminal. Dual-booting Ubuntu is not necessary unless you encounter specific WSL2 limitations that block platform operation.

### Workstation Upgrade Path

| Upgrade | When | Cost | Impact |
|---------|------|------|--------|
| **RAM: 64 GB → 128 GB DDR5** | When FalkorDB graph exceeds 32 GB | ~$200–300 (2 more 32 GB DIMMs) | Allows FalkorDB 64 GB + comfortable headroom for containers. Also enables larger CPU offload for 70B models |
| **SSD: Add 3rd NVMe volume (if needed)** | When RAID 0 volume fills up (likely Phase 6+) | ~$130 | Additional capacity. The 2-volume setup comfortably handles Phase 0–5 projections |
| **GPU: RTX 5090 → future gen** | 2–3 years, if VRAM increases significantly | $2,000+ | Next-gen consumer GPUs may have 48+ GB VRAM, enabling 70B fully in VRAM |
| **Network: Add 10 GbE NIC** | If the onboard NIC is only 2.5 GbE and NAS access is slow | ~$30–80 (PCIe 10GbE) | Faster bulk data access from NAS during ingestion |

---

## Tier 2: NAS (Bulk Archival Storage — Phase 5+)

> **Trigger**: Purchase a NAS only when total NVMe usage approaches 70% of combined capacity (~4.2TB across 6TB). With projected Year 1 usage of 3–7 TB total across all data categories, the full archive may approach this threshold at Phase 5 scale — though active working data is significantly smaller. See [06-deployment.md § NAS Migration](06-deployment.md) for the migration procedure.

The NAS serves a single role: **persistent bulk storage** with data protection. All compute (Docker containers, LLM inference) stays on the AMD workstation. This simplifies NAS selection — no need for a powerful CPU, Docker support, or large RAM. Any reliable NAS with sufficient bays is sufficient.

### Hardware Specification

| Component | Specification |
|-----------|--------------|
| **Chassis** | 10-bay NAS (e.g., Synology DS1821+, QNAP TS-h1090FU, or similar) |
| **Drives** | 10 × 16–32 TB HDD (enterprise-grade, e.g., Seagate Exos X20/X24, WD Ultrastar HC560/HC680) |
| **RAID** | RAID 6 (dual parity — tolerates any 2 drive failures) |
| **CPU** | Any (NAS-class is fine — not running compute workloads) |
| **RAM** | 8–16 GB (sufficient for file serving and RAID operations) |
| **Network** | 10 GbE (for fast connectivity to AMD workstation) |
| **Cache** | Optional NVMe SSD cache (2 × 1–2 TB) for read caching of frequently accessed data |

> **Simplified from original design**: Since Docker workloads run on the AMD workstation, the NAS no longer needs a Xeon/EPYC CPU, 64 GB RAM, or Docker/Container Station support. This opens up significantly cheaper NAS options.

### Storage Capacity Analysis

#### Raw vs. Usable

| Configuration | Raw | RAID 6 Parity | Usable | Formatted (~5% overhead) |
|--------------|-----|---------------|--------|-------------------------|
| 10 × 16 TB | 160 TB | 32 TB | **128 TB** | **~122 TB** |
| 10 × 20 TB | 200 TB | 40 TB | **160 TB** | **~152 TB** |
| 10 × 32 TB | 320 TB | 64 TB | **256 TB** | **~243 TB** |

> **Recommendation**: 10 × 16 TB is sufficient (6–16× projected Year 5 needs) and saves $2,500–4,000 vs. 32 TB drives. RAID 6 supports online capacity expansion.

#### Projected Storage Consumption

| Data Category | Estimated Size | Growth Rate | Notes |
|---------------|---------------|-------------|-------|
| **FalkorDB RDB snapshots** | 15–50 GB | Moderate | In-memory DB persists via RDB dumps. 800K+ nodes + 3M+ relationships |
| **FalkorDB AOF/WAL** | 10–30 GB | Moderate | Write-ahead log before compaction |
| **SEC filings archive** | 1–3 TB | ~200 GB/yr | 5,000+ companies × ~20 filings × avg 5 MB. Includes 13F filings |
| **News article archive** | 50–200 GB | ~50 GB/yr | Article text + metadata |
| **Financial data** | 5–20 GB | ~5 GB/yr | Structured JSON/CSV from APIs |
| **Country economic data** | 5–20 GB | ~5 GB/yr | World Bank, IMF, BLS, BEA datasets |
| **Congressional disclosures** | 2–10 GB | ~2 GB/yr | STOCK Act filings (2012–present) |
| **13F institutional holdings** | 20–100 GB | ~20 GB/yr | Quarterly filings for 500+ institutions |
| **Government contracts** | 10–50 GB | ~10 GB/yr | USAspending.gov data |
| **Legislation & policy** | 5–20 GB | ~5 GB/yr | Bills, rules, executive orders |
| **Langfuse Postgres** | 10–100 GB | ~20 GB/yr | LLM traces, costs |
| **Docker images** | 10–20 GB | Stable | FalkorDB, Langfuse, Postgres, app containers |
| **LLM model weights** | 100–500 GB | Occasional | Primarily ≤70B GGUF files for RTX 5090 |
| **Backups & snapshots** | 50–200 GB | Proportional | FalkorDB snapshots, Postgres dumps |
| **Document uploads** | 10–100 GB | Variable | User-uploaded PDFs, reports |
| **Scraped web content** | 20–100 GB | ~20 GB/yr | Raw HTML + Markdown conversions |
| **Total (Year 1)** | **~3–7 TB** | | 6TB NVMe comfortably handles this. Active working set is much smaller than full archive |
| **Total (Year 5, projected)** | **~8–20 TB** | | NAS handles bulk overflow; NVMe keeps hot data |

> **Year 1 on NVMe**: 6TB NVMe (2 volumes: 2TB P41 + 4TB SN5000 RAID 0) provides generous headroom vs. ~3–7 TB Year 1 projection. The RAID 0 array has no parity — a NAS backup is especially important for the raw data and model weights stored there. The full historical backfill is the primary driver toward the NAS trigger.

#### Verdict: Is 256 TB Enough?

**Yes — by a very wide margin.** Even at aggressive projections, the platform will use under 20 TB over 5 years. Even 10 × 16 TB (128 TB usable) provides **6–16× headroom**.

### NAS Services

The NAS runs **no compute workloads**. It serves SMB shares to the AMD workstation (mounted in WSL2 via `cifs-utils`). All Docker containers run on the workstation.

| NAS Service | Purpose |
|-------------|--------|
| **SMB file shares** | Expose archive data, model weights, and backup volumes to workstation |
| **Snapshot scheduling** | Automated BTRFS/ZFS snapshots of all shares |
| **RAID management** | Health monitoring, scrubbing, drive replacement |
| **Backup target** | Receives periodic `rsync` of `./data/` from workstation |

### Volume Mount Structure (NAS)

The NAS exports SMB shares that the AMD workstation mounts in WSL2:

```bash
# WSL2 mount (using cifs-utils)
sudo mount -t cifs //nas/investment-researcher /mnt/nas -o credentials=/etc/smbcredentials
```

```
/volume1/investment-researcher/       # On the NAS
├── archive/
│   ├── filings/                      # SEC filing archive (10-K, 10-Q, 8-K)
│   ├── filings-13f/                  # 13F institutional holdings filings
│   ├── congressional/                # Congressional disclosure PDFs + parsed data
│   ├── legislation/                  # Bills, regulations, executive orders
│   ├── contracts/                    # Government contract records
│   ├── economic-data/                # World Bank, IMF, BLS, BEA datasets
│   ├── news/                         # News article archive
│   └── scraped/                      # Web scraping archive
├── models/                           # Full model weight library
└── backups/
    ├── data/                         # rsync mirror of workstation ./data/
    └── config/                       # docker-compose.yml, .env backups
```

> **Note**: FalkorDB data, Langfuse Postgres, and application databases remain on the **workstation's local NVMe** for performance. The NAS stores backups and bulk archival data that doesn't need NVMe speed.

### NAS-Level Data Protection

| Feature | Configuration |
|---------|--------------|
| **RAID level** | RAID 6 — survives any 2 simultaneous drive failures |
| **Scrubbing** | Monthly RAID scrub to detect silent data corruption |
| **Snapshots** | Daily BTRFS/ZFS snapshots of all volumes (retained 30 days) |
| **Backup** | Weekly full backup of critical data (FalkorDB RDB, Postgres dump, config) to separate volume or external target |
| **UPS** | Recommended — protects NAS during power loss |
| **Drive replacement** | Hot-swap support. Replace failed drive, RAID rebuilds automatically |

---

## Tier 3: Mac Studio Cluster (Future — Phase 6+ Only)

> **Gate**: Do NOT purchase Mac Studios until Phase 5 is complete and the following conditions are met:
> 1. The platform is producing valuable research insights consistently
> 2. Quantitative evidence that 32B models on RTX 5090 are insufficient (quality benchmarks)
> 3. Revenue from monetization streams (see [09-monetization-strategy.md](09-monetization-strategy.md)) justifies the investment
> 4. OR: Inference API monetization demand exceeds RTX 5090 capacity

### Why Mac Studios (Not More GPUs)?

The Mac Studio's advantage is **memory capacity**, not speed. If the platform demonstrates that 405B-class models significantly outperform 32B for KG construction or multi-hop reasoning — something that can only be determined empirically in Phase 5 — then Mac Studios are the most practical way to run 405B locally.

| Scenario | Recommendation |
|----------|---------------|
| 32B models are sufficient for all tasks | **Skip Mac Studios entirely**. Keep RTX 5090. Save $16K–40K |
| 70B is needed for KG construction quality | **Buy 1 Mac Studio** (512 GB). Run 70B at Q8 or FP16. ~$8K–10K |
| 405B significantly outperforms 70B | **Buy 2 Mac Studios**. Run 405B at Q8 distributed. ~$16K–20K |
| Inference API monetization demand is high | **Buy 2–4 Mac Studios**. Dedicated capacity for paying users |

### Hardware Specification

| Component | Per Unit | Cluster (2 units) | Cluster (4 units) |
|-----------|----------|--------------------|--------------------|
| **Model** | Mac Studio (M4 Ultra or later) | | |
| **Unified Memory** | 512 GB | 1 TB | 2 TB |
| **CPU Cores** | 24 performance + efficiency | 48+ | 96+ |
| **GPU Cores** | 80 (M4 Ultra) | 160 | 320 |
| **Neural Engine** | 32-core | 64-core | 128-core |
| **SSD** | 2–4 TB (for local model cache) | 4–8 TB | 8–16 TB |
| **Interconnect** | Thunderbolt 5 (120 Gbps) | Daisy-chain or switch | Mesh or switch |
| **Network** | 10 GbE to NAS | 10 GbE to NAS | 10 GbE to NAS |

### Distributed Inference via RDMA

Apple Silicon's Thunderbolt 5 supports **RDMA** (Remote Direct Memory Access), enabling ultra-low-latency, zero-copy memory access between Mac Studios. This allows treating multiple machines as a single pool of unified memory for model inference.

#### Distributed Inference Stack

```
┌────────────────────────────────────────────────────────┐
│             OpenAI-Compatible API Endpoint              │
│                  (http://mac-cluster:8000/v1)           │
└───────────────────────┬────────────────────────────────┘
                        │
┌───────────────────────┴────────────────────────────────┐
│                   exo / MLX Distributed                 │
│                                                         │
│  Model layers partitioned across Mac Studios:           │
│                                                         │
│  ┌─────────────┐ TB5/RDMA ┌─────────────┐              │
│  │ Mac Studio 1│◄────────►│ Mac Studio 2│              │
│  │ Layers 0-39 │          │ Layers 40-79│              │
│  │ 512 GB      │          │ 512 GB      │              │
│  └─────────────┘          └─────────────┘              │
│                                                         │
│  (Optional: 4-unit mesh for 405B models)                │
│  ┌─────────────┐ TB5/RDMA ┌─────────────┐              │
│  │ Mac Studio 3│◄────────►│ Mac Studio 4│              │
│  │ Layers 0-N  │          │ Layers N-M  │              │
│  │ 512 GB      │          │ 512 GB      │              │
│  └─────────────┘          └─────────────┘              │
└─────────────────────────────────────────────────────────┘
```

#### Inference Frameworks

| Framework | Role | Notes |
|-----------|------|-------|
| **[exo](https://github.com/exo-explore/exo)** | Distributed inference across Apple Silicon | Automatic peer discovery, model partitioning, OpenAI-compatible API. Supports Thunderbolt networking |
| **[MLX](https://github.com/ml-explore/mlx)** | Apple's native ML framework | Optimized for Apple Silicon unified memory. Fast token generation. Used by `mlx-lm` for text generation |
| **[mlx-lm](https://github.com/ml-explore/mlx-examples)** | MLX-based language model serving | Single-node serving. Can be used per-node within exo cluster |
| **[llama.cpp](https://github.com/ggerganov/llama.cpp)** | Alternative inference engine | Metal backend for Apple Silicon. RPC feature for multi-node. More mature ecosystem |

**Recommended**: **exo** as primary (easiest multi-node setup with auto-discovery), with **llama.cpp** as fallback.

### Model Capacity Analysis

| Model | Parameters | Quantization | Memory Required | Fits On |
|-------|-----------|-------------|-----------------|---------|
| Llama 3.1 8B | 8B | Q8 | ~9 GB | 1 Mac Studio (plenty of room) |
| Llama 3.1 70B | 70B | Q4_K_M | ~42 GB | 1 Mac Studio |
| Llama 3.1 70B | 70B | Q8 | ~75 GB | 1 Mac Studio |
| Llama 3.1 70B | 70B | FP16 | ~140 GB | 1 Mac Studio |
| Qwen 2.5 72B | 72B | Q4_K_M | ~43 GB | 1 Mac Studio |
| Qwen 2.5 72B | 72B | FP16 | ~144 GB | 1 Mac Studio |
| DeepSeek-R1 671B | 671B | Q4_K_M | ~400 GB | 1 Mac Studio (512 GB, tight) |
| Llama 3.1 405B | 405B | Q4_K_M | ~240 GB | 1 Mac Studio, or distributed across 2 |
| Llama 3.1 405B | 405B | Q8 | ~430 GB | Distributed across 2 Mac Studios |
| Llama 3.1 405B | 405B | FP16 | ~810 GB | Distributed across 2 Mac Studios |

#### Key Insight
With **2× Mac Studios (1 TB total)**, you can run:
- Llama 3.1 405B at Q8 quantization (near-lossless)
- Or multiple 70B models concurrently (one per Studio) for parallel agent workloads
- Or DeepSeek-R1 671B at Q4 quantization across the cluster

With **4× Mac Studios (2 TB total)**, you can run:
- Llama 3.1 405B at full FP16 precision
- Or 2–3 different 70B models simultaneously for model routing / specialization
- Enormous headroom for any current open-weight model

### Recommended Model Strategy (Phase 6+, Mac Studios)

These recommendations apply only once Mac Studios are purchased and the workstation is no longer the primary inference engine:

| Workload | Model (Target) | Quantization | Deployment | Notes |
|----------|----------------|-------------|------------|-------|
| **KG construction** (GraphRAG-SDK) | Llama 3.1 405B or Qwen 2.5 72B | Q8 | Distributed / single Studio | KG construction needs strongest reasoning. 405B is ideal |
| **Complex agents** (Ripple Effect, Synthesizer) | Llama 3.1 405B or 70B | Q8 | Distributed / single Studio | Multi-hop reasoning benefits from larger models |
| **Light agents** (Triage, Data Monitor) | Llama 3.1 8B | Q8 | **RTX 5090 on workstation** | Keep light models on the fast GPU. Free Mac Studios for heavy models |
| **NL→Cypher** (GraphRAG-SDK queries) | Llama 3.1 70B | Q8 | Single Studio | Code generation is strong at 70B |
| **Embeddings** | nomic-embed-text or mxbai-embed-large | FP16 | **RTX 5090 on workstation** | Lightweight, run on whichever machine has capacity |

> **Hybrid model**: With both RTX 5090 and Mac Studios available, run light/fast workloads (8B routing, embeddings, classification) on the GPU for maximum speed, and heavy workloads (405B KG construction, multi-hop reasoning) on Mac Studios. This is the best of both worlds.

### Network Configuration (Full Deployment)

When Mac Studios are added, the network expands:

```
Developer Mac ─── 10GbE/1GbE ─┐
                               │
NAS ─── 10GbE ─────────────────┤─── 10GbE Switch
                               │
AMD Workstation ── 10GbE ──────┤    (Docker host + RTX 5090)
                               │
Mac Studio 1 ── 10GbE ─────┤
Mac Studio 2 ── 10GbE ─────┤    (Future: 405B inference)
Mac Studio 3 ── 10GbE ─────┤
Mac Studio 4 ── 10GbE ─────┘

Mac Studio 1 ═══ TB5 ═══ Mac Studio 2    (Thunderbolt 5 for RDMA inference)
Mac Studio 3 ═══ TB5 ═══ Mac Studio 4    (Thunderbolt 5 for RDMA inference)
```
```

- **10 GbE**: All machines on a 10 GbE switch for API traffic, SMB access, and general connectivity
- **Thunderbolt 5**: Direct TB5 cables between Mac Studios for RDMA-based distributed inference (120 Gbps)
- **Workstation**: Serves as Docker host; Mac Studios only serve inference
- **API routing**: Application containers on the workstation call either `localhost:8000` (RTX 5090) or `mac-studio-1.local:52415` (Mac cluster) depending on model requirements

### Mac Cluster API Integration (Phase 6+)

When Mac Studios are added, the cluster exposes an OpenAI-compatible API endpoint alongside the workstation's existing endpoint:

```
# exo startup on Mac Studio 1 (coordinator)
exo run llama-3.1-405b-instruct

# Application config — add Mac cluster as secondary endpoint
LLM_PRIMARY_MODEL=openai/qwen2.5-32b-instruct         # RTX 5090 (fast, interactive)
LLM_HEAVY_MODEL=openai/llama-3.1-405b-instruct         # Mac cluster (heavy reasoning)
LLM_LIGHT_MODEL=openai/llama-3.1-8b-instruct           # RTX 5090 (routing, classification)
LLM_API_BASE=http://localhost:8000/v1                   # Workstation vLLM
LLM_HEAVY_API_BASE=http://mac-studio-1.local:52415/v1   # Mac cluster exo
LLM_EMBEDDING_MODEL=nomic-embed-text
LLM_EMBEDDING_API_BASE=http://localhost:8001/v1          # Workstation CPU/GPU
```

> **Model routing via LiteLLM**: Configure LiteLLM to route requests based on model name — `qwen2.5-32b` goes to the workstation, `llama-405b` goes to the Mac cluster. The application layer doesn't need to know which backend serves which model.

---

## Thermal & Power Considerations

### Phase 0–4 (Workstation Only)

| Device | Typical Power Draw | Heat Output | Notes |
|--------|-------------------|-------------|-------|
| AMD Workstation (CPU + RTX 5090 under load) | 400–650 W | Significant | RTX 5090 alone draws up to 575 W TDP. 360mm AIO handles CPU. Ensure case fans are running for GPU exhaust |
| AMD Workstation (idle / light load) | 80–150 W | Low | When not running inference, power draw is modest |
| **Phase 0–4 Total** | **~400–650 W peak** | | Standard 15A household circuit is fine |

### Phase 5 (Add NAS)

| Device | Additional Power | Notes |
|--------|-----------------|-------|
| NAS (10-bay, loaded) | 80–150 W | Storage-only NAS draws less than a compute NAS |
| 10 GbE Switch (or basic switch) | 10–40 W | |
| **Phase 5 Total** | **~550–850 W peak** | | Standard 15A household circuit is fine |

### Phase 6+ (Add Mac Studios)

| Device | Additional Power | Notes |
|--------|-----------------|-------|
| Mac Studio (M4 Ultra, under load) | 200–370 W each | Compact. Needs clearance around vents |
| Mac Studio cluster (2 units) | 400–740 W | |
| Mac Studio cluster (4 units) | 800–1,480 W | |
| **Full deployment total** | **~1,400–2,500 W peak** | Dedicated 20A circuit recommended |

### Cooling Recommendations
- Dedicated room or closet with ventilation
- Ambient temperature below 27°C / 80°F
- Workstation case needs unobstructed front intake and rear exhaust (the Lancool 237 has good airflow)
- RTX 5090 exhausts heat into the case — ensure top/rear case fans are exhaust
- Mac Studios need 10+ cm clearance around all vents (if purchased)
- NAS drives run cooler with front-to-back airflow; avoid enclosed cabinets without airflow

---

## Estimated Budget

### Already Purchased

| Item | Cost |
|------|------|
| AMD Workstation (Ryzen 9 9950X3D, 64 GB DDR5, RTX 5090 32 GB, SK Hynix P41 2TB NVMe, 1200W PSU, built) | **~$3,764** |
| WD Blue SN5000 2 TB NVMe × 2 | **~$200–260** |

### Phase 0–4: Immediate Costs (Workstation Only)

| Item | Qty | Est. Unit Price | Est. Total |
|------|-----|----------------|------------|
| UPS (1000–1500 VA) | 1 | $200–$400 | $200–$400 |
| OpenAI API costs (Phase 0–1, supplemental) | — | — | $100–$500 |
| **Phase 0–4 Total (new purchases)** | | | **$300–$900** |
| **Phase 0–4 Total (including workstation)** | | | **$4,064–$4,664** |

### Phase 5: NAS Purchase (When NVMe Hits 70%)

| Item | Qty | Est. Unit Price | Est. Total |
|------|-----|----------------|------------|
| NAS chassis (10-bay, storage-only) | 1 | $500–$1,500 | $500–$1,500 |
| 16–32 TB enterprise HDD | 10 | $250–$700 | $2,500–$7,000 |
| 10 GbE switch (or basic gigabit) | 1 | $30–$500 | $30–$500 |
| 10 GbE NIC for workstation (if needed) | 1 | $30–$80 | $30–$80 |
| **Phase 5 Total (NAS only)** | | | **$3,060–$9,080** |

### Phase 6+: Mac Studio Expansion (If Validated)

| Item | Qty | Est. Unit Price | Est. Total |
|------|-----|----------------|------------|
| Mac Studio M4 Ultra (512 GB) | 1–2 | $8,000–$10,000 | $8,000–$20,000 |
| Thunderbolt 5 cables (2m) | 1–3 | $50–$80 | $50–$240 |
| **Phase 6+ Total** | | | **$8,050–$20,240** |

### Total Cost by Scenario

| Scenario | Total Investment | Notes |
|----------|-----------------|-------|
| **Validation (workstation only, Phase 0–4)** | **$4,100–$4,700** | Already-purchased workstation + UPS + API costs. No NAS needed yet |
| **+ NAS (Phase 5)** | **$7,100–$13,700** | When NVMe hits 70%. 16 TB drives = low end, 32 TB = high end |
| **+ 1 Mac Studio (Phase 6)** | **$15,200–$23,700** | For 70B/405B models |
| **+ 2 Mac Studios** | **$23,200–$33,700** | Full local inference stack |
| **+ 4 Mac Studios (monetization)** | **$39,200–$53,700** | Maximum scale for inference API monetization |

> **Cost comparison to original plan**: The original 2-tier architecture (NAS with Docker + Mac Studios) estimated $25,000–$94,000. The workstation-first architecture brings the **validation cost to just $300–$900** in new purchases (UPS + API costs), since the workstation is already owned. NAS and Mac Studios are deferred until the platform proves their value.

---

## NAS Selection Criteria

Since Docker workloads now run on the AMD workstation, NAS requirements are significantly simpler:

| Requirement | Why |
|-------------|-----|
| **10-bay or more** | 10 × 16–32 TB RAID 6 |
| **10 GbE built-in or add-in** | Fast file serving to workstation (large SEC filings, model weights). If starting with 1 GbE, upgrade later as data grows |
| **BTRFS or ZFS** | Snapshot and data integrity features |
| **Hot-swap bays** | Replace failed drives without downtime |
| **SMB support** | File sharing to workstation via WSL2 `cifs-utils` (Windows-native protocol) |

> **No longer required**: Docker/Container Station, powerful CPU, 64 GB RAM, NVMe cache slots. This opens up the entire prosumer NAS market.

### Recommended Models (as of early 2026)

| Model | Bays | Price Range | Pros | Cons |
|-------|------|-------------|------|------|
| **Synology DS1821+** | 8 (+2 expansion) | $900–$1,100 | Mature software, easy setup, BTRFS snapshots, 10 GbE add-in card slot | Only 8 bays native (but expansion unit available) |
| **Synology DS1823xs+** | 8 | $1,400–$1,700 | 10 GbE built-in, Ryzen CPU, NVMe cache slots | 8 bays |
| **QNAP TS-873A** | 8 | $800–$1,000 | Affordable, 2.5 GbE built-in, good software | 8 bays, 2.5 GbE only (add 10 GbE card) |
| **Synology DS3622xs+** | 12 | $2,500–$3,500 | 12 bays, 10 GbE, enterprise-grade | Overkill for storage-only role |
| **TrueNAS SCALE** (DIY) | Any | $500–$1,500 (parts) | ZFS, free software, unlimited customization | Requires building/configuring yourself |
| **Used enterprise NAS** | 12–24 | $300–$800 | Very cheap bays-per-dollar | Noisy, power-hungry, may lack modern features |

> **Budget pick**: A Synology DS1821+ (~$1,000) with 10 × 16 TB drives (~$2,500) gives you 128 TB usable in RAID 6 for ~$3,500 total. That's the sweet spot for this project.
>
> **DIY pick**: A TrueNAS SCALE build with a used server chassis and ZFS gives maximum flexibility and the best price-per-TB, but requires more setup time.
