# 共用 HTTP/1.1 契約 v1

所有服務監聽 `0.0.0.0:8080`（可用 PORT 改寫），關閉存取日誌、TLS、壓縮與下游自動重試。GET `/health` 回傳 200 `{"status":"ok"}`。JSON 物件欄位順序及空白不計入正確性。

- POST `/json`：Content-Type 必須為 `application/json`（允許參數）；body 為恰好四欄的物件：`id` 是 0..4294967295 整數、`name` 是 1..32 個 ASCII 英數字或底線、`values` 是恰好 16 個 -1000..1000 整數、`padding` 是恰好 896 個 `x`。回傳 200 JSON：相同 id、name、padding，以及即時計算的 `sum`（取代 values）。請求／回應約 1 KiB。
- POST `/cpu`：相同 Content-Type；body 恰好只有整數 `seed`（0..4294967295）。每次從 seed 開始，執行恰好 100,000 輪 `x = (1664525 * x + 1013904223) mod 2^32`，回傳 200 `{"result":x}`。不得預先計算或快取。
- GET `/io`：每次恰好對 `DOWNSTREAM_URL`（完整 URL，例如 http://downstream:8080/data）發出一次 HTTP GET。下游等待至少 20ms 後回傳恰好 1024 個 ASCII `x`。服務完整讀取並驗證狀態及內容後，回傳 200 `application/octet-stream` 與相同 bytes。下游逾時 1500ms，禁止 redirect、retry、壓縮。異常回傳 502 `{"error":"downstream_error"}`。

錯誤依優先序：未知路徑 404 `not_found`；已知路徑錯誤 method 405 `method_not_allowed`；已知路徑帶非空 query 400 `invalid_request`；POST 非 JSON Content-Type 415 `unsupported_media_type`；body 超過 4096 bytes 413 `payload_too_large`；解析或 schema 錯誤 400 `invalid_request`。錯誤 JSON 格式為 `{"error":"<code>"}`。GET body 不參與契約。路徑比對大小寫敏感，不解碼 percent escape。

數字採數學整數語意，`1.0`、`1e0` 可接受；布林不可當作整數。不接受 NaN/Infinity、BOM、非 UTF-8 或多份 JSON；重複 key 採最後值（JSON schema 驗證在解析後執行）。測試使用可精確表示於 IEEE-754 的數值；不以極端精度浮點字面值比較 parser 行為。

`schema.json` 的 `$defs.cpuRequest` 與 `$defs.jsonRequest` 提供機器可讀 schema。`fixtures.json` 為所有語言共用的正常、邊界與無效測試資料。`tools/contract.py` 也驗證 malformed JSON、body 上限、method、media type、query 和下游錯誤。壓測用相同 schema，依種子動態生成 id/name/seed，並逐筆驗證結果。
