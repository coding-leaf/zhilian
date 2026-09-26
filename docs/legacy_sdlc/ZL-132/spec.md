# Spec: 资料上传、状态轮询与分页重拍前端组件 - 技术契约

- **关联 Intent**: ZL-132
- **主导设计人**: TechLead
- **当前状态**: Approved
- **Change Tier**: Tier 2 (单模块特性演进 / 前端分包业务组件与交互流)

---

## 1. 架构流向与设计方案

本模块为智练微信小程序资料业务分包（`miniprogram/src/subpackages/material/`），承载资料的列表浏览、文件导入（微信文件/相册拍摄）、异步解析状态轮询、版本切换与单页 OCR 门禁就地重拍交互。

严格遵循 `AGENTS.md` 与 `docs/DESIGN.md`：
1. **纯单向数据流**：页面/组件触发动作 $\rightarrow$ `src/api/material.ts` 发起请求 $\rightarrow$ 同步更新 Pinia `materialStore` 内存状态 $\rightarrow$ 视图响应式驱动；
2. **分包与文件尺寸红线**：所有业务视图与组件收敛于 `miniprogram/src/subpackages/material/` 分包，主包体积保持零膨胀；任何单 `.vue` 或 `.ts` 文件行数严格 $\le 300$ 行；
3. **视觉与交互规范**：零 Unicode Emoji、深蓝主交互色 (`#2563EB`)、冷灰底色 (`#F8FAFC`)；
4. **面向用户的零度文案**：绝对禁止呈现“乱码率21%”、“BM25”等底层算法术语，严格对齐 `DESIGN.md` 字典（如“第 4 页文字模糊，需重新拍摄”）；
5. **安全与内存保护**：严禁持久化资料与切片全文至本地 Storage；轮询器遵循 Vue 生命周期强绑定，组件卸载时立即清理定时器。

### 1.1 模块拓扑与组件流向

```mermaid
flowchart TD
    subgraph Pages[分包页面 (subpackages/material/pages/)]
        P_List["list/index.vue (资料列表 / 空状态 / 上传触发)"]
        P_Detail["detail/index.vue (资料详情 / 状态徽章 / 版本切换 / 考点入口)"]
    end

    subgraph Components[业务组件 (subpackages/material/components/ <=300行)]
        C_Card["MaterialCard.vue (卡片展示 / 状态标签 / 操作栏)"]
        C_Upload["MaterialUpload.vue (微信文件/拍照上传弹窗 / 幂等防重)"]
        C_Drawer["RetakeDrawer.vue (不合格页展示 / 剩余重拍次数 / 就地重拍)"]
    end

    subgraph Composables[生命周期与轮询调度]
        Hook_Poll["useMaterialPolling.ts (2s 指数退避/定频轮询 / 自销毁守护)"]
    end

    subgraph State[Pinia 内存状态层]
        Store["materialStore.ts (materials, activeMaterialId, activeVersionId)"]
    end

    subgraph API[统一接口层 (src/api/material.ts)]
        API_List["fetchMaterialList()"]
        API_Detail["fetchMaterialDetail()"]
        API_Upload["uploadMaterialFile()"]
        API_Status["fetchMaterialStatus()"]
        API_Reshoot["reshootMaterialPage()"]
        API_Delete["deleteMaterial()"]
    end

    P_List --> C_Card
    P_List --> C_Upload
    P_Detail --> C_Drawer
    P_Detail --> Hook_Poll
    Hook_Poll --> API_Status
    Hook_Poll --> Store
    C_Upload --> API_Upload
    C_Drawer --> API_Reshoot
    P_List --> API_List
    P_Detail --> API_Detail
    API_List & API_Detail & API_Upload & API_Reshoot --> Store
```

### 1.2 页面与组件职责拆解（全部 $\le 300$ 行）

| 文件路径 | 职责与交互边界 | 行数上限与约束 |
| :--- | :--- | :--- |
| `subpackages/material/pages/list/index.vue` | 资料列表展示、下拉刷新、触底加载（20条/页）、空状态插画与引导、新建导入浮动按钮（FAB） | $\le 250$ 行，使用 `MaterialCard` 渲染列表项 |
| `subpackages/material/pages/detail/index.vue` | 资料详情元数据（格式、大小、时间）、激活版本切换下拉、页面切片状态概要、知识点大纲入口（跳转 ZL-133）、异常页重拍抽屉触发器 | $\le 280$ 行，挂载 `useMaterialPolling` 监听解析中状态 |
| `subpackages/material/components/MaterialCard.vue` | 单条资料卡片：标题、文件类型图标、当前状态胶囊（`wd-tag`）、创建时间、点击跳转详情、右滑或更多操作（删除） | $\le 180$ 行，遵循 `DESIGN.md` 卡片阴影与圆角 |
| `subpackages/material/components/MaterialUpload.vue` | 导入对话框：选择来源（微信会话文件 `wx.chooseMessageFile` 或 手机相册/拍照 `uni.chooseImage`）、自定义标题输入、上传中进度环、Idempotency-Key 幂等守卫 | $\le 240$ 行，上传前本地尺寸校验，调用 `uploadMaterialFile` |
| `subpackages/material/components/RetakeDrawer.vue` | 异常页就地重拍抽屉（`wd-popup`）：展示不合格页码与零度原因（“第 X 页文字模糊，需重新拍摄”）、展示剩余重拍次数（限 3 次）、拍照重新上传并调用重拍接口 | $\le 220$ 行，重拍达标自动更新状态，熔断达到 3 次禁用重拍按钮并提示重新上传 |
| `subpackages/material/composables/useMaterialPolling.ts` | 智能状态轮询组合式函数：资料处于 `pending` / `parsing` 时以 2000ms 间隔请求后端状态；状态转为 `ready` / `failed` 或达到超时限制（默认 60s）自动终止；`onUnmounted` 强力清理定时器防内存泄漏 | $\le 120$ 行，纯逻辑封装 |

---

## 2. API 与数据契约设计

严格与后端 `backend/app/api/v1/materials.py` 接口契约物理绑定。

### 2.1 接口路由与数据流定义

#### (1) 资料上传并创建解析 (`POST /api/v1/materials/upload`)
- **请求方法**: `POST` (Multipart / Form-Data)
- **请求头**: `Authorization: Bearer <token>`, `Idempotency-Key: <uuid-v4>` (防并发重击)
- **表单参数**:
  - `file`: 二进制文件数据流 (PDF, DOCX, PNG, JPG)
  - `title`: `string | undefined` (资料标题，默认原文件名)
  - `source_type`: `"local" | "wechat"`
- **响应 Schema (`MaterialUploadResponse`)**:
  ```typescript
  export interface MaterialUploadResponse {
    id: string;              // UUIDv4
    version_id: string;      // UUIDv4
    title: string;
    file_format: string;
    file_size: number;
    source_type: 'local' | 'wechat';
    status: 'pending' | 'parsing' | 'ready' | 'failed';
    created_at: string;
  }
  ```

#### (2) 资料分页检索 (`GET /api/v1/materials`)
- **请求方法**: `GET`
- **Query 参数**: `page: number (>=1)`, `page_size: number (default 20)`, `keyword?: string`, `status?: string`
- **响应 Schema (`MaterialListResponse`)**:
  ```typescript
  export interface MaterialListItem {
    id: string;
    title: string;
    file_format: string;
    file_size: number;
    source_type: string;
    status: 'pending' | 'parsing' | 'ready' | 'failed';
    current_version_id: string | null;
    created_at: string;
    updated_at?: string;
  }
  export interface MaterialListResponse {
    items: MaterialListItem[];
    total: number;
    limit: number;
    offset: number;
  }
  ```

#### (3) 资料详情与状态轮询 (`GET /api/v1/materials/{id}`)
- **请求方法**: `GET`
- **Path 参数**: `id: string` (UUIDv4)
- **响应 Schema (`MaterialDetailResponse`)**:
  ```typescript
  export interface MaterialDetailResponse {
    id: string;
    title: string;
    file_format: string;
    file_size: number;
    source_type: string;
    status: 'pending' | 'parsing' | 'ready' | 'failed';
    current_version_id: string | null;
    versions_count: number;
    created_at: string;
    updated_at: string;
  }
  ```
- *注：后端状态查询通过 `GET /api/v1/materials/{id}` 复用，返回实时的 `status` 与 `current_version_id`。*

#### (4) 单页 OCR 就地重拍质检 (`POST /api/v1/materials/{id}/reshoot`)
- **请求方法**: `POST` (Multipart / Form-Data)
- **Path 参数**: `id: string` (资料 UUID)
- **表单参数**:
  - `file`: 二进制图片文件流 (重拍的 PNG/JPG 单页图片)
  - `page_index`: `number` (从 1 开始的页码序号)
  - `version_id`: `string | undefined` (指定版本 UUID)
- **响应 Schema (`MaterialReshootResponse`)**:
  ```typescript
  export interface MaterialReshootResponse {
    material_id: string;
    version_id: string;
    page_index: number;
    is_qualified: boolean;
    reshoot_count: number;       // 0 ~ 3
    parse_status: string;        // 'ready' | 'failed' | 'parsing'
    unqualified_reason?: string | null;
  }
  ```

#### (5) 资料软删除 (`DELETE /api/v1/materials/{id}`)
- **请求方法**: `DELETE`
- **Path 参数**: `id: string`
- **响应 Schema**:
  ```typescript
  export interface MaterialDeleteResponse {
    material_id: string;
    is_deleted: boolean;
    permanent: boolean;
    message: string;
  }
  ```

### 2.2 前端 API 封装扩展 (`miniprogram/src/api/material.ts`)

在现有 `miniprogram/src/api/material.ts` 基础上，补充以下标准调用契约：
```typescript
/** 上传资料文件并携带幂等键 */
export function uploadMaterialFile(params: {
  filePath: string;
  title?: string;
  sourceType?: 'local' | 'wechat';
  idempotencyKey?: string;
  onProgressUpdate?: (progress: number) => void;
}): Promise<ApiResponse<MaterialUploadResponse>>;

/** 单页重拍替换并重触发 OCR 门禁 */
export function reshootMaterialPage(params: {
  materialId: string;
  pageIndex: number;
  filePath: string;
  versionId?: string;
}): Promise<ApiResponse<MaterialReshootResponse>>;
```

### 2.3 异常映射与零度文案字典 (Copywriting Mapping)

前端必须将后端 HTTP 状态码或业务错误码转换为对用户友好的零度自然文案：

| 错误场景 / 接口返回 | 后端业务错误码 / HTTP | UI 面向用户自然文案 (严格遵循 DESIGN.md) |
| :--- | :--- | :--- |
| 单页重拍超过 3 次触发熔断 | `40002` (ReshootLimitExceeded) | `该页重拍已达 3 次上限，文字仍不达标，建议重新上传更清晰的原文件` |
| 资料解析 OCR 识别不合格 | `page.unqualified_reason` | `第 {page} 页文字模糊，需重新拍摄` (严禁出现“乱码率21%”) |
| 资料未包含有效文本或过短 | `40001` (QualityCheckError) | `资料内容字数较少或格式无法识别，请检查后重试` |
| 资料正在解析中 | `status == 'parsing'` | `正在智能提取考点大纲，通常需要几秒钟...` |
| 文件格式不受支持 | `10001` / HTTP 422 | `目前仅支持 PDF、DOCX 及图片格式文件` |
| 上传文件大小超出限制 | HTTP 413 | `文件体积过大，请上传小于 20MB 的文件` |

---

## 3. 可测性设计 (Design for Testability)

### 3.1 独立纯函数计算核 (`src/subpackages/material/utils/copywriting.ts`)
解耦出 100% 纯函数，用于单测无桩覆盖：
- `formatPageUnqualifiedReason(pageIndex: number, rawReason?: string | null): string`：将底层后端质检不合格描述转换为面向用户的“第 N 页文字模糊，需重新拍摄”；
- `computeRemainingReshoots(reshootCount: number): number`：安全计算剩余重拍次数 `Math.max(0, 3 - reshootCount)`；
- `resolveMaterialStatusTag(status: MaterialStatus): { text: string; type: 'primary' | 'success' | 'warning' | 'danger' }`：根据状态输出对应的 `wd-tag` 呈现属性。

### 3.2 外部依赖与 Mock 策略
1. **微信与 Uni 原生 API 打桩 (`tests/setup.ts`)**：
   - `uni.uploadFile`：模拟文件上传网络请求，支持触发 `onProgressUpdate` 回调，并模拟 200/400/413 等返回值；
   - `wx.chooseMessageFile` / `uni.chooseImage`：模拟从微信聊天列表或相册选取临时路径对象；
   - `uni.showToast` / `uni.showModal`：桩函数收集调用参数，便于 Vitest 断言确认弹窗；
2. **定时器与轮询 Mock (`vi.useFakeTimers()`)**：
   - 在 `useMaterialPolling` 单元测试中通过快进时间（`vi.advanceTimersByTime(2000)`）验证轮询调用次数、状态转为 `ready` 自动停止及销毁清理。

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 全局轮询 vs 页面 Composable 局部轮询
- **方案 A (全局轮询器)**：在 Pinia `materialStore` 中维护全局 Poller，切换页面依然保持后台请求。
  - *缺点*：无法感知页面销毁；用户离开资料详情页后仍在后台向服务器刷接口，造成移动端无意义耗电、流量浪费与服务器压力；易产生内存泄漏。
- **方案 B (页面局部 Composable，采纳)**：在 `detail/index.vue` 中调用 `useMaterialPolling`，与页面生命周期强绑定（`onUnmounted` 清理）。
  - *优点*：生命周期完全受控，用户离开立即释放定时器，遵循端侧资源节约原则与 KISS 原则。

### 4.2 集中大页面 vs 拆解组件组合
- **方案 A (单页面集中实现)**：将上传弹窗、重拍抽屉、列表与卡片写在同一个 `index.vue`。
  - *缺点*：单个文件行数必然突破 600 行，直接践踏 `AGENTS.md`（<=300行）红线，维护性极差。
- **方案 B (组件化离散拆解，采纳)**：拆分为 `list/index.vue`、`detail/index.vue`、`MaterialCard.vue`、`MaterialUpload.vue`、`RetakeDrawer.vue`。
  - *优点*：各组件单一职责，最大单文件约 250 行，极易进行单独的组件测试与样式审查。

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 5.1 7 维动态风险扫描矩阵

| 风险维度 | 扫描评估结论 | 缓解与防护对策 |
| :--- | :--- | :--- |
| **Files** | 仅新增 `miniprogram/src/subpackages/material/` 目录内文件，微调 `api/material.ts` 与 `pages.json` | 范围明确，不破坏其他主包文件与现有组件 |
| **Public API** | 后端接口在 ZL-119 / ZL-127 中均已稳定实现并经过测试 | 前端严格适配现有路由与 DTO，不变更任何后端协议 |
| **Data Schema** | 不涉及数据库或持久化 Schema 变更 | 前端 Storage 白名单严格生效，禁止将资料全文落盘 |
| **Auth & Security** | 上传与重拍必须携带有效 JWT Token，且后端已存在多租户隔离 | 复用 `src/utils/request.ts` 自动 Bearer 注入与 401 静默刷新机制 |
| **Dependencies** | 无新增 npm 依赖，全面复用现有的 `wot-design-uni` 与 `pinia` | 不增加依赖冲突与安全漏洞风险 |
| **Rollback Difficulty**| 低。分包代码与主应用低耦合 | 若遇重大缺陷，可直接回滚 Git 提交，不影响已发布的答题主链路 |
| **Blast Radius** | 仅限于学习资料上传管理业务分包 | 智练工作台首页与练习主链路不受影响 |

### 5.2 回滚与故障应急策略
- **本地回滚**：Git 单 Commit 回退，直接撤销分包页面与路由注册；
- **降级保护**：当 OCR 解析服务由于算力异常出现大面积堆积时，`useMaterialPolling` 设置最大 30 次（60s）超时保护，超时后向用户提示“解析排队中，请稍后下拉刷新查看”，防止客户端无线死循环。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)
- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Accepted
- **签批人 / 日期**: TechLead (人类授权模式) / 2026-09-25 02:05

