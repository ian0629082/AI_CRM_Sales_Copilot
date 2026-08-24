"""把 FastAPI 的 OpenAPI schema 匯出成 JSON，供前端生成 TypeScript 型別。

不需要啟動 uvicorn —— 直接從 app 物件取出 schema 即可。

用法（在 backend 目錄下）：
    python -m scripts.export_openapi

輸出到 frontend/openapi.json，接著在 frontend 執行 npm run gen:api
就會生成 src/types/api.ts。

這條流程的價值：後端改了欄位，前端 tsc 立刻報錯，
而不是等到 Demo 時才發現畫面空白。
"""

import json
import pathlib

from app.main import app

OUTPUT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    paths = len(schema.get("paths", {}))
    print(f"OpenAPI schema 已匯出：{OUTPUT}")
    print(f"  路徑數：{paths}")


if __name__ == "__main__":
    main()
