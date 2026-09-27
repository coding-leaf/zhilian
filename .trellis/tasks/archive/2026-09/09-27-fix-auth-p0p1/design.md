# 修复设计：AUTH 切片 P0+P1

## 1. 边界与原则

- 契约权威：后端强类型 Settings（`.trellis/spec/backend/quality-guidelines.md` 场景「Secret Resolution Must Go Through Strongly-Typed Settings」）。
- 鉴权为安全敏感改动：先红后绿，不弱化测试。
- AUTH-001 后端为主；AUTH-002/003 跨层（前端为主，后端防御性收口）。

## 2. 真实契约（已核实）

### 密钥
- `AppSettings.model_config = SettingsConfigDict(env_prefix="ZHILIAN_", env_file=".env")`（`config.py:421-426`）→ `secret_key` 的环境变量名为 **`ZHILIAN_SECRET_KEY`**，默认 `"zhilian-development-secret-key-32bytes-min!"`（`config.py:398-401`）。
- 现状缺陷：`security.py:41` `os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)`，`DEFAULT_SECRET_KEY` 为另一硬编码串（`security.py:30`）。裸 `SECRET_KEY` 与 `ZHILIAN_SECRET_KEY` 无交集 → 生产注入被忽略。
- 读取入口应为 `get_settings().secret_key.get_secret_value()`；`create_access_token`/`create_refresh_token`/`decode_token` 已有显式 `secret_key` 入参优先逻辑（`security.py:79,117,141`）。

### 登录
- 前端 `login.vue:62-65` 固定 `nickname: '学员用户'`；`loginByWechat` 直接透传（`api/auth.ts:18-27`）。
- 后端 `services/auth.py:185-190`：老用户 `if nickname is not None or avatar_url is not None: update_profile(...)` → 前端必传非空即覆盖。

### 401
- `request.ts:263-266`：`is401 = statusCode === 401 || resData.code === 20001`；`if (is401 && !isRefreshUrl) return handle401Error(options)`。登录 `skipAuth:true` 但 url 非 refresh → 进入 `handle401Error` → 无 `refresh_token` 时 `redirectToLogin()` + 抛“登录状态已过期”（`request.ts:140-146`）。

## 3. 方案设计

### 3.1 AUTH-001（backend）

`core/security.py`：
```python
from app.core.config import get_settings

def get_secret_key(*, secret_key: str | None = None) -> str:
    if secret_key is not None:
        return secret_key
    return get_settings().secret_key.get_secret_value()
```
- 移除裸 `os.getenv("SECRET_KEY", ...)` 读取路径；保留 `DEFAULT_SECRET_KEY` 常量仅用于**生产 fail-fast 判定**（改名为 `INSECURE_DEVELOPMENT_SECRET_KEY` 或复用 config 默认值比较）。
- 需明确“开发默认密钥”的唯一判定源：以 `AppSettings.secret_key` 的默认值（`zhilian-development-secret-key-32bytes-min!`）为准，新增 `config.is_insecure_default_secret()` 或常量。
- 生产 fail-fast：在应用启动路径（`app/main.py` lifespan 或 `app/container.py` 装配）调用校验：`if settings.env == "production" and is_default_secret: raise RuntimeError(...)`。
- `security.py` 内 `DEFAULT_SECRET_KEY` 若不再被引用则删除，避免双默认值漂移。

测试：
- `tests/unit/core/test_security.py` 中依赖裸 `SECRET_KEY` 的用例（如 `:199-203`）改为经 Settings 注入（`monkeypatch.setenv("ZHILIAN_SECRET_KEY", ...)` + `get_settings.cache_clear()`）。
- 新增：仅 `ZHILIAN_SECRET_KEY` 生效断言；生产默认密钥 fail-fast 断言。

### 3.2 AUTH-002（cross-layer）

前端：
- `pages/auth/login.vue` 调用 `loginByWechat({ code })`，**不带** `nickname`/`avatar_url`（类型改为可选）。
- 若未来接入 `uni.getUserProfile` 真昵称，再按需传；本任务不引入。

后端（防御性收口，避免空值/占位覆盖）：
- `services/auth.py:185-190`：仅当字段**非空**时更新，且不得用空串覆盖已有非空值：
```python
if (nickname is not None and nickname.strip()) or (avatar_url is not None and avatar_url.strip()):
    self.user_repo.update_profile(user.id, nickname=nickname, avatar_url=avatar_url)
```
- 更稳妥：`update_profile` 内部对 `None` 字段跳过（保持既有），并在 service 层过滤空串。**不得**硬编码“学员用户”这类占位。

测试：
- 后端：二次登录未传 nickname → 既有昵称保持不变（新增用例；现有用例 `test_auth_service.py:53-71` 断言“显式传参会覆盖”，保留）。

### 3.3 AUTH-003（frontend）

`utils/request.ts`：
- 计算 `const isAnonymous = options.skipAuth === true;`
- 401 分支改为：`if (is401 && !isRefreshUrl && !isAnonymous) return handle401Error(...)`；匿名端点直接落入非 2xx 分支，抛出后端真实 `code`/`message`（`AppError(errorCode, errorMsg)`）。
- 保证匿名失败路径**不** `storage.removeItem('auth_tokens')`、**不** `redirectToLogin()`。
- `login.vue` catch 已展示 `err.message`，修复后即可显示真实原因（如“用户账号已被停用”）。

测试（vitest）：
- mock 登录 401/20001 → 断言抛出 `AppError` 且 code/message 为后端值；`redirectToLogin`（uni.reLaunch）**未被调用**；`auth_tokens` 未被清除。
- 回归：非匿名请求 401 仍走静默刷新逻辑（既有用例保持）。

## 4. 影响面与兼容

| 文件 | 变更 |
|---|---|
| `backend/app/core/security.py` | 密钥读取改 Settings；移除裸 env 路径 |
| `backend/app/core/config.py` | 新增默认密钥判定助手/常量（如需要） |
| `backend/app/main.py` 或 `container.py` | 生产 fail-fast 校验 |
| `backend/app/services/auth.py` | 登录画像更新收口（非空才更新） |
| `backend/tests/unit/core/test_security.py` | 密钥用例改真实契约 + 新增回归 |
| `backend/tests/unit/services/test_auth_service.py` | 新增昵称保留回归 |
| `miniprogram/src/pages/auth/login.vue` | 不再传硬编码昵称 |
| `miniprogram/src/utils/request.ts` | 匿名端点 401 不刷新/不重定向 |
| `miniprogram/tests/unit/utils/request.spec.ts`、`tests/unit/pages/login.spec.ts` | 新增回归 |

- 兼容：显式 `secret_key` 入参语义不变；`skipAuth` 请求仅在失败路径行为更正确；登录请求减少字段（后端可选字段，兼容）。

## 5. 验证 & 回归

先红后绿断言：
1. 仅 `ZHILIAN_SECRET_KEY` → `get_secret_key()` 与 Settings 一致（红：现返回默认串）。
2. 生产 + 默认密钥 → 启动校验抛错。
3. 后端：老用户二次登录不传 nickname → 昵称不变（红：现状不触发更新其实也因此保留；**关键红**在于“传占位会覆盖”——断言前端不再传占位 + 后端空值不覆盖）。
4. 前端：匿名登录 401 → 抛真实错误、不重定向、不清 token（红：现状清 token 并重定向）。

门禁：后端五项 + 前端三项全绿。

## 6. 回滚点

- 密钥改动集中在 `security.py` + 启动校验，可回退。
- 前端 401 分支为单点条件扩展，可回退。
- 若发现部署实际使用裸 `SECRET_KEY`，须先与用户确认迁移（本设计按项目 `ZHILIAN_` 约定为准）。
