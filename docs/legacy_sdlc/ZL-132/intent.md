# Intent: 资料上传、状态轮询与分页重拍前端组件

- **任务编号**: ZL-132
- **提出人**: TechLead
- **创建时间**: 2026-09-25 01:25
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
在 ZL-131 中，小程序已完成基础脚手架、Pinia 4-Store、网络请求客户端与 Storage 白名单封装。
后端在 ZL-119 / ZL-127 中已经实现了资料导入、多版本管理、OCR 质检门禁（乱码率/字数检查）、分页重拍熔断（最多3次）、状态轮询与 MinIO 直传/存储 API。
然而前端目前尚未实现资料模块的实际页面与交互组件。用户无法在小程序中导入学习资料（上传 PDF/图片）、无法观察资料的异步切片解析与 OCR 门禁状态（2秒智能轮询）、无法获知不合格页面的具体异常，更无法针对不合格页进行就地单页拍照重拍与重新校验。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **分包路由与页面结构 (`miniprogram/src/subpackages/material/`)**：
   - 严格遵循 `docs/DESIGN.md` 要求：资料管理相关页面全部置于 `subpackages/material/` 分包中；
   - 包含资料列表主页 (`pages/list/index.vue`)、资料详情与解析状态页 (`pages/detail/index.vue`)；
2. **核心业务交互组件与功能**：
   - **资料导入组件** (`components/MaterialUpload.vue`)：支持微信从聊天记录选择文件 (PDF/DOCX) 或本地拍照/相册选择多张图片；调用上传接口并支持幂等键（Idempotency-Key）；
   - **状态轮询与反馈** (`composables/useMaterialPolling.ts`)：在解析中或重拍后启动 2s 间隔的定时轮询，解析完成或失败时自动停止并同步至 `materialStore`；页面离开时主动销毁定时器；
   - **分页门禁与重拍抽屉** (`components/RetakeDrawer.vue`)：按页展示 OCR 门禁状态，高亮不合格页面（如“第 4 页文字模糊，需重新拍摄”）；提供单页就地重拍并提交接口 (`POST /materials/{id}/pages/{page_no}/retake`)；展示剩余重拍次数（限 3 次）；
   - **资料卡片与列表** (`components/MaterialCard.vue`)：展示资料标题、版本、创建时间、当前状态徽章（已解析/解析中/待重拍/解析失败）、进入知识点/练习入口。
3. **规范与限制**：
   - 严格遵循 `docs/DESIGN.md`：零 Unicode Emoji、深蓝交互色 (`#2563EB`)、冷灰底色 (`#F8FAFC`)；
   - 文案严格使用 `docs/DESIGN.md` 第 5 节的自然文案字典（严禁“乱码率21%”等底层术语，统一使用“第 4 页文字模糊，需重新拍摄”）；
   - 单文件代码行数严格控制在 300 行以内；
   - 资料原文与切片绝对严禁写入本地 Storage；
   - 具备完整 Vitest 单元测试与组件交互测试。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严禁单文件超过 300 行，复杂视图必须拆分为独立子组件；
  - 必须置于 `subpackages/material/` 分包，严禁膨胀小程序主包；
  - 严禁向本地 Storage 写入资料全文；
  - 轮询逻辑必须具备组件卸载自动清理防护，防止后台内存泄漏与无用网络请求；
  - 遵循零 Emoji、低饱和度色盘。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不涉及知识点树展示与题目生成界面（属于 ZL-133）；
  - 不涉及练习答题与交卷（属于 ZL-134）；
  - 不修改后端代码。
* **完成判定条件 (Definition of Done)**:
  - `subpackages/material/` 页面与组件完整实现；
  - 资料列表、上传、详情、轮询、重拍抽屉完整协同；
  - `materialStore` 状态同步与更新正常；
  - 单元测试与组件测试通过；
  - `cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit` 全部通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 小程序上传二进制文件在测试中通过 mock `uni.uploadFile` 模拟进度与成功返回。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead (人类授权模式) / 2026-09-25 01:28
