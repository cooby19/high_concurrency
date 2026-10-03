# 實作驗證紀錄

日期：2026-10-03。這是開發環境功能驗證，不是正式容量比較。

## 已驗證

- 六個正式模式服務映像與獨立下游映像全部成功建置。
- 18 個單元／工具測試通過，涵蓋 CPU 獨立 oracle、失敗聯集、逾時、內容錯誤、固定到達率、未發送請求、排程延遲、容量搜尋、重複測量、恢復視窗、cgroup counters 與敏感檔案忽略規則。
- 六種語言各通過 57 個共用契約案例（1 vCPU / 4 GiB），以及各 32 個同時 I/O 請求；每筆成功 I/O 恰好對應一次下游呼叫。
- 六種語言各通過下游 503、redirect、1500ms 逾時、錯誤內容、斷線五種故障模式；不跟隨 redirect 或重試。
- 六種語言另外以四 worker／runtime processor 設定、單核資源配額通過契約及 16 筆同時 CPU 請求，驗證多 worker 路徑。此項不是四核效能測試。
- Go 單核端到端 smoke：JSON／CPU／I/O，各三次確認、一次縮短穩定性與一次縮短突發測試，共 15 輪；全部 valid、SLO pass、零內容錯誤；產出 12 張 SVG 圖表與 Markdown 報告。
- Python 語法檢查與 `git diff --check` 通過。

## 環境限制

Docker 僅提供 3 CPU，六個實際 4 vCPU 配額測項明確跳過。正式 runner 會預先拒絕資源不足的主機，不將單核／多 worker 測試代替四核結果。

沒有三台分離主機，因此未執行完整正式矩陣、正式 30 分鐘穩定性測試或正式 60 秒超載／300 秒恢復測試。smoke 使用固定 10 RPS，只驗證流程；沒有搜尋最大容量，也不作語言排名。

暖機穩定性需要依每輪保存的視窗人工判讀；若尚未穩定，所有語言須使用統一延長的暖機時間重跑。

## 重現命令

```sh
python3 -m tools.containers
HC_INTEGRATION=1 python3 -m unittest discover -s tests -v
python3 -m tools.suite contract/local.json --smoke --languages go --cpus 1 --output results/go-smoke
```

執行 smoke 前需依 README 啟動 `hc-downstream`。完整整合測試需要至少 4 CPU 才不會跳過四核配額測項。原始結果與本機報告保存在 `results/go-smoke/`，依專案規則不提交；報告內清楚標示 LOCAL VALIDATION ONLY 與開發中 dirty source 狀態。
