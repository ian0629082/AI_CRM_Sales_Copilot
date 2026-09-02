"""評估腳本的終端機輸出設定。"""

import sys


def force_utf8_output() -> None:
    """把 stdout/stderr 切成 UTF-8。

    Windows 的終端機預設是 cp950，印到一個它編不出來的字元（例如「⋯」）
    就會整支腳本掛掉 —— 而且是掛在 print 那一行，不是掛在做事的地方。

    這件事第一次發生在跑期末考的時候。期末考只能跑一次，
    當時如果那行 print 出現在呼叫模型**之後**，就會變成
    「錢花了、結果沒寫出來、資料集也不乾淨了」。它剛好在之前，純屬運氣。

    所以這不是「加一個環境變數就好」的小事：
    一支會因為終端機編碼而中斷的腳本，遲早會在最不能中斷的時候中斷。

    errors="replace" 是刻意的 —— 真的遇到編不出來的字元就印個問號，
    絕對不要因為顯示問題而讓一次花了錢的執行失敗。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
