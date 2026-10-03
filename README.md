# 多語言高併發比較

依照 [H_C_plan.md](H_C_plan.md) 實作 Go、Java、C#、Node.js、Python、Rust 的同等工作負載。比較單位是「語言＋runtime＋HTTP stack＋設定」，不產生跨情境總排名。

驗證結果與環境限制見 [VALIDATION.md](VALIDATION.md)。

## 已實作

- [共用契約](contract/spec.md)、共用正常／邊界／錯誤測資，以及六種可獨立建置的服務。
- JSON API、100,000 輪 uint32 CPU 運算、一次獨立 20ms HTTP 下游呼叫。
- 1 vCPU / 4 GiB 與 4 vCPU / 4 GiB；worker 與子程序全部在同一容器 cgroup。
- 固定到達率產生器、逐筆內容驗證、2 秒完整請求逾時、排程延遲及未送出請求記錄。
- 容量倍增／減半／二分搜尋、三次交錯隨機確認、同絕對 RPS 曲線、穩定性與過載恢复。
- 原始 JSONL、完整設定／commit／image ID、CPU／throttling／memory 時間序列、Markdown / SVG 報告。

## 技術選擇

| 語言 | HTTP stack | 多核方式 |
|---|---|---|
| Go | net/http | GOMAXPROCS |
| Java 21 | JDK HttpServer + Gson | virtual threads，ActiveProcessorCount |
| C# / .NET 9 | ASP.NET Core Kestrel | managed thread pool，DOTNET_PROCESSOR_COUNT |
| Node 22 | node:http | cluster worker / CPU |
| Python 3.12 | aiohttp | process / CPU，SO_REUSEPORT |
| Rust | Axum / Tokio / reqwest | Tokio worker / CPU；CPU 工作使用限量 blocking pool |

版本與建置參數見 [builds.json](contract/builds.json)。Rust 包含 Cargo.lock；Python 依賴含間接套件固定版本。這是一組凍結的比較基準版本，不表示各 runtime 的最新版本。C# 以官方 SDK archive 建置，採 globalization invariant 模式（本契約只接受 ASCII name）。

## 建置與快速驗證

需要 Linux、Docker（cgroup v2）、Python 3.12+。六個工具鏈映像與建置快取需要充足磁碟；使用 vfs storage driver 時尤其如此，可於建置完成後清理不再使用的 build cache。所有命令在 repository 根目錄執行。Docker 預設使用本機 `/var/run/docker.sock`。

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r tools/requirements.txt
python -m tools.containers
python -m unittest discover -s tests -v
HC_INTEGRATION=1 python -m unittest discover -s tests -v
```

雲端環境若有 `CODEX_PROXY_CERT`，建置工具會用 BuildKit secret 傳入 CA；不將 CA 或 credentials 寫進映像。Docker 設定目錄唯讀時可設 `BUILDX_CONFIG=/tmp/hc-buildx`，保持原有 Docker 登入與代理設定。

整合測試會建立專用 `hc-test-*` 容器、使用 18080/18081 port，驗證六語言兩種配額與下游 503／redirect／逾時／錯誤內容／斷線，最後清理。單元測試中的本機 HTTP server 也需要 socket 權限。

## 執行單一服務與壓測

```sh
docker network create hc-bench
docker run -d --name hc-downstream --network hc-bench -p 8081:8080 hc-downstream
docker run -d --name hc-example --network hc-bench -p 8080:8080 \
  --cpus 1 --memory 4g --memory-swap 4g \
  -e WORKERS=1 -e DOWNSTREAM_URL=http://hc-downstream:8080/data hc-node
python -m tools.contract http://127.0.0.1:8080 --downstream http://127.0.0.1:8081
python -m tools.load http://127.0.0.1:8080 json --rps 100 --seconds 10 --output results/example
# 在 suite 前移除使用相同 port 的範例容器
docker rm -f hc-example
```

## 自動矩陣

```sh
# 先啟動上述 hc-downstream；所有語言映像須已建置
python -m tools.suite contract/local.json --smoke --output results/smoke
# 可縮小驗證語言範圍，但不是完整正式比較
python -m tools.suite contract/local.json --smoke --languages go --cpus 1 --output results/go-smoke
python -m tools.report results/smoke
```

`--smoke` 使用 1 秒暖機、2 秒量測、固定 10 RPS，執行兩組資源與三情境，包含三次確認與縮短的穩定性／突發測試。若主機少於 4 核，可用 `--cpus 1` 驗證單核流程；整合測試會明確跳過無法配置的 4 核測項。只驗證管線，不把 10 RPS 當成搜尋出的正式容量。輸出目錄必須不存在，避免覆蓋既有結果。

正式模式須將 load、target、downstream 放在 **三台不同 Linux 主機**。先在 target 建置六語言映像，在 downstream 建置並啟動下游映像。使用相同受測主機逐一測試所有語言。下游與壓測機應有足夠額外資源，記錄實際硬體。

複製 `contract/local.json` 到專案外的設定檔：

- `mode` 設為 `formal`。
- `target.url` 設為受測主機的 HTTP URL；`target.docker` 設為 `["ssh", "benchmark-target", "docker"]`，`target.host_command` 設為 `["ssh", "benchmark-target"]`。
- `downstream.url` 是下游根 URL；`downstream.data_url` 是受測服務可連線的完整 `/data` URL；`downstream.host_command` 設為 `["ssh", "benchmark-downstream"]`。
- 移除 `network`（僅供同主機 Docker bridge）。SSH alias／金鑰由專案外 SSH config 管理；command prefix 使用上述格式，不放 credentials。
- 將設定凍結後執行 `python -m tools.suite /path/to/config.json --output results/formal`。

正式流程會核對三台主機 boot ID、拒絕未提交的程式、記錄實際映像 ID，對每個情境／配額從 100 RPS 找到 ≤5% 的通過／失敗區間。每點重建容器、暖機 120 秒、量測 300 秒；容量確認三次皆達標，否則降 5% 重做。各輪隨機化語言順序。接著量測固定 `curve_rates`（預設 100/200/400，各三次）、80% 容量 1800 秒，以及先於 50% 容量暖機，再以 150% 容量 60 秒後降到 50% 最多 300 秒。

暖機是否穩定仍需檢視保存的暖機視窗。若未穩定，統一增加 `warmup_seconds`，對整個比較組重跑。硬體／OS／映像／任何參數變更都要重跑受影響組別。這個完整矩陣需要很長時間，不能用本機 smoke 結果宣称正式排名。

## 有效性與統計細節

- 每個排程時間獨立於前一請求完成時間；排程落後超過 `max_lag_ms`（預設 10ms）或滿 `max_inflight`（預設 10000）記為 dropped。含 dropped 或超額發送延遲的 run 無效，搜尋中止，不能解讀為服務容量。
- I/O 下游實際等待 p99 必須 ≤25ms（20ms + 凍結的 5ms 容忍值）；超標 run 無效。`/metrics` 為內部測試介面，不應暴露公網。
- 失敗率是非 200、timeout、連線錯誤、內容錯誤的聯集；內容錯誤一筆就不達標。總延遲包含完整回應與 client 連線取得，另呈現成功／失敗延遲。
- 延遲以 0.1ms 向上取整 histogram 保存，避免長測試的記憶體跟請求數線性成長；原始 JSONL 保留實際精度。吞吐量以量測時段排程請求為 cohort，最多額外等待 2 秒 drain，完成數除以原量測時間；另記含 drain 的 wall time。
- 每秒讀取容器 cgroup，包含所有 worker／child；CPU seconds／千筆正確請求、CPU cores、throttled seconds、常態／尖峰記憶體與 OOM 都記錄。memory.peak 包含暖機。採样本身有少量開銷，各語言設定一致。
- 壓測端 CPU seconds／peak RSS 與發送延遲保存在每輪 summary。若壓測端／網路／下游成為瓶頸，改善基礎設施再重測，不放宽門檻來取得排名。
- 恢復需要完整、連續三個 10 秒視窗皆滿足 p99≤200ms、失敗率≤0.1%、零內容錯誤；缺失結果不視為恢復。
- 不平均不同輪次的 p99；保留每輪數值與中位數／範圍。容量點的有效吞吐量範圍重疊時標為差異未明確；探索點不直接排名。

產物在 `results/`，預設不提交。正式資料應另外歸檔保存 `manifest.json`、`runs.json`、`capacities.json`、各輪原始／暖機／resources 檔及 SVG，連同對應 Git commit、凍結設定與映像匯出／registry digest。所有敏感資訊必須留在專案外。
