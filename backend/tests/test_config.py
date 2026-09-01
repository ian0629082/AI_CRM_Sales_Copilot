"""設定載入的測試（Sprint 7）。

這一份守的是**「設定壞掉的時候，錯誤訊息會不會順手洩漏別的設定」**。

它來自一次真實的部署失敗：Render 上少設了 DATABASE_URL，
pydantic 的錯誤訊息把「目前已經讀到的設定」整個 dict 附在後面，
於是 JWT_SECRET 的值被印進了 build log。

啟動失敗本身是預期中的（少設變數就該擋下來），
真正的問題是那個懲罰被放大成「其餘所有祕密一起曝光」。
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# 長度足夠通過 JWT_SECRET 驗證的假值。刻意寫得一眼看得出是測試用的。
FAKE_SECRET = "test-only-alpha-bravo-charlie-delta-echo-foxtrot"

# pydantic 印值的時候會把長字串**截斷成頭尾**，中間用 ... 取代：
#
#     input_value={'JWT_SECRET': 'test-only...echo-foxtrot'}
#
# 所以「完整字串不在訊息裡」這個斷言，在還沒修正的版本上**也會通過** ——
# 一個永遠是綠的測試，比沒有測試更糟，因為它讓人以為這件事有人在守。
# 要比對的是頭尾片段，那才是真的會外洩的部分。
SECRET_HEAD = FAKE_SECRET[:10]
SECRET_TAIL = FAKE_SECRET[-10:]


def test_missing_setting_does_not_leak_other_values(monkeypatch: pytest.MonkeyPatch):
    """少設一個變數時，錯誤訊息不能連別的變數的值一起吐出來。

    這是 Sprint 6「登入失敗要遮罩 email」的同一條原則，
    只是戰場換到了啟動階段：看得到 build log 的人比看得到資料庫的人多得多。
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET", FAKE_SECRET)

    # _env_file=None：不要讀開發機上的 .env，否則這個測試在有 .env 的機器上
    # 會因為讀到真實設定而不成立。
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    message = str(exc_info.value)

    # 查問題需要的資訊要留著：是哪個欄位缺了。
    assert "DATABASE_URL" in message

    # 不需要的資訊不能留：其他欄位的值，含被截斷後仍看得到的頭尾。
    assert SECRET_HEAD not in message
    assert SECRET_TAIL not in message


def test_error_still_says_which_field_is_missing(monkeypatch: pytest.MonkeyPatch):
    """遮蔽不能遮到「連是哪個欄位都看不出來」。

    一則說不出原因的啟動失敗，會讓人只能一個一個變數試，
    那比洩漏更浪費時間 —— 遮蔽與可查性要同時成立才算做對。
    """
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@host/db")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "JWT_SECRET" in str(exc_info.value)


def test_short_jwt_secret_is_rejected_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
):
    """弱密鑰要擋下來，但訊息裡不能出現那把密鑰本身。

    「太短」這件事不需要把值印出來就講得清楚，
    而被擋下的密鑰往往正是使用者接下來會改長一點繼續用的那一把。
    """
    short_secret = "too-short-secret"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@host/db")
    monkeypatch.setenv("JWT_SECRET", short_secret)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    message = str(exc_info.value)

    assert "JWT_SECRET" in message
    assert "32" in message  # 要講清楚門檻是多少
    assert short_secret not in message
