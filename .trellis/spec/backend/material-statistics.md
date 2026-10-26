# 个人页学习足迹统计契约

> 事实源：`backend/app/repositories/material.py::get_statistics`、`backend/app/services/material.py::get_statistics`、`backend/app/api/v1/materials.py::get_material_statistics`、`miniprogram/src/pages/profile/`。
> 最后核对：2026-10-04。

## 1. Scope / Trigger

修改个人页「学习足迹」、用户级资料统计接口或资料/考点计数条件时，必须核对本契约。课程聚合不是用户总量：未分类资料不会进入任何课程分组，课程计数求和会漏掉它们。

## 2. Signatures

```python
MaterialRepository.get_statistics(*, user_id: UUID) -> tuple[int, int]
MaterialService.get_statistics(*, user_id: UUID) -> tuple[int, int]
# GET /api/v1/materials/statistics
# MaterialStatisticsResponse
{"ready_material_count": 4, "knowledge_point_count": 51}
```

两元组顺序为就绪资料数、考点数。路由必须在 `/{material_id}` 前注册，避免 `statistics` 被作为 UUID 解析。

前端使用 `apiGetMaterialStatistics()`；已建课程使用 `apiListFolders(false)` 返回的未归档列表长度。页面专属请求状态不从其他页面的缓存课程列表推导。

## 3. Contracts

- 接口无分页、无需请求体，必须鉴权；响应字段必填且为非负整数。
- 就绪资料数：`Material.user_id == 当前用户`、`is_deleted == false`、`status == ready`。
- 考点数：上述资料下的 KnowledgePoint 实体数，同时限制 `KnowledgePoint.user_id`；不额外筛选激活版本。
- 计入未分类资料和归档课程内的资料。归档只是课程整理，未删除的就绪资料仍属于学习资产。页面说明资料统计包含归档课程。
- 已建课程仅含未归档课程。课程数与资料数表达不同对象，不要求归档范围相同。
- 既有课程考点聚合没有 `ready` 条件，本任务保持其行为；不得用它的分组求和替代新接口。
- 独立标量聚合避免多考点 JOIN 倍增资料数；固定查询数，不逐资料查询。
- 个人页 `onShow` 重取、下拉刷新后停止动画。登录态、首次加载、请求失败和成功零值应分别显示；失败有重试动作。
- 课程列表与资料统计全部成功后才展示完整数字。退出或切换账号后，旧请求不得提交旧账号的结果；失败不应固化为零值。
- `useLearningStatistics` 先完成 `/folders`（其既有服务会清理逾期归档课程），再读取资料统计；不能并发跨清理前后取数。`LearningStatisticsCard` 消费 `LearningStatisticsState`，不自行发请求。

## 4. Validation & Error Matrix

| 条件 | 接口/页面行为 |
| --- | --- |
| 未鉴权 | 走现有鉴权错误契约；个人页未登录时不请求统计 |
| 当前用户无就绪资料 | 两项统计返回 0；页面展示成功零值 |
| 软删除或非 ready 资料 | 资料及其考点均不计入 |
| 归档课程/未分类的 ready 资料 | 正常计入 |
| 考点属于其他用户 | 不计入 |
| 任一统计加载请求失败 | 显示加载失败及重试入口，不冒充无数据 |
| 退出/换账号时旧请求完成 | 丢弃过期结果 |

## 5. Good / Base / Bad Cases

- Good：1 份课程资料 + 3 份未分类 ready 资料显示 4 份讲义，考点为这 4 份的实体总数。
- Base：从未上传资料的已登录用户成功请求后显示零值；未登录用户显示登录后查看提示。
- Bad：对课程列表求和漏算未分类资料，或加载失败后仍渲染三个 0。

## 6. Tests Required

- 真实数据库查询测试课程/未分类/归档资料、删除与非 ready 条件、租户隔离。
- 同一资料挂多个考点时，资料数仍为 1；考点计数不依赖资料版本是否激活。
- API 验证鉴权和静态路由优先级，成功零值响应符合 schema。
- 前端行为测试未登录、加载、成功零值、任一请求失败与可重试、两种刷新、陈旧账号请求。
- 生产构建中个人页配置 `enablePullDownRefresh: true`。

## 7. Wrong vs Correct

```ts
// Wrong：未分类资料从未进入课程分组；失败时空数组又会伪装成零值。
const readyCount = folders.reduce((total, folder) => total + folder.ready_material_count, 0)

// Correct：用户级统计由后端直接聚合；页面另行维护明确的请求状态。
const statistics = await apiGetMaterialStatistics()
const readyCount = statistics.ready_material_count
```
