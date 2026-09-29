# 界面截图

| 项 | 值 |
| --- | --- |
| 采集日期 | 2026-09-29 |
| 采集方式 | 微信开发者工具自动化（`miniprogram-automator` 驱动，非手工截图） |
| 模拟器 | 363 × 785，统一机型 |
| 数据 | 全部来自真实后端（账号下 2 门课程、3 份已解析资料、21 道题、2 次练习、8 条错题） |

不采用 `docs/demo/index.html`——那是设计阶段的原型，与真实运行界面不是一回事。

## 清单

| # | 文件 | 页面 | 路由 | 体现的内容 |
| --- | --- | --- | --- | --- |
| 01 | `01-workbench.png` | 工作台 | `pages/index/index` | 课程分类与课程级操作、导入入口、**课程全景刷题（77 个核心考点）**、资料列表与解析状态 |
| 02 | `02-material-detail.png` | 资料详情 | `subpackages/material/pages/course/index?id=<资料ID>` | 解析就绪状态、**抽取 31 个考点的拓扑图谱**（L1/L2/L3 分层）、按知识点组卷出题入口 |
| 03 | `03-upload.png` | 导入资料 | `subpackages/material/pages/upload/index` | 支持的资料格式说明（**该页本身只有说明文案，实际上传入口在工作台卡片上**） |
| 04 | `04-question-review.png` | 核对出题 | `subpackages/material/pages/questions/index?material_id=<资料ID>` | **考点范围 31 个全选**、题型多选、题量与难度设置、智能出题入口 |
| 05 | `05-question-bank.png` | 题库（学情 Tab） | `pages/review/index` | 学情全景（待攻克 8 / 已消灭 0）、我的练习与判题状态、错题巩固与举一反三 |
| 06 | `06-wrong-book.png` | 错题本 | 同上（下滚） | 错题列表：题型徽标、巩固状态、题干、记录时间、针对本考点出题 |
| 07 | `07-profile.png` | 个人中心 | `pages/profile/index` | **学习足迹：2 已建课程 / 3 就绪讲义 / 77 涵盖考点** |
| 08 | `08-practice-session.png` | 作答中 | `subpackages/practice/pages/session/index?practice_id=<练习ID>` | 进度 1/7、答题卡、**选项选中态**、上一题/下一题 |
| 09 | `09-diagnosis-report.png` | 诊断报告 | `subpackages/report/pages/detail/index?practice_id=<练习ID>` | 得分 4/12、得分率 33%、错题数、**四个薄弱考点的掌握度与巩固建议** |
| 10 | `10-login.png` | 登录页 | `pages/auth/login` | 未登录初始态 |

## 采集实现要点

自动化脚本放在**仓库之外**（不引入 `miniprogram-automator` 依赖到本仓库的 `package.json`，
避免污染 CI）。三个必须知道的坑：

1. **`miniprogram-automator` 的 `launch()` 在 Node 22 上必然失败**：Node 不允许直接 `spawn` `.bat`，
   而该库内部正是直接 spawn `cli.bat`。绕开方式是自己用 shell 起
   `cli.bat auto --project <产物目录> --auto-port 9420`，再用 `automator.connect({ wsEndpoint })` 连它。
2. **开发者工具需要开启「服务端口」**（设置 → 安全设置），否则 CLI 会报「工具的服务端口已关闭」并退出。
3. **页面参数名是 `folder_id` / `material_id` / `practice_id`**，不是 `folder` / `material` / `practice`。
   传错名字页面**不报错**，只是渲染空态——所以脚本必须校验落点路径，否则会把上一个页面当成目标页面拍下来。

## 三条硬要求

1. **必须拍到真实数据，不要空态。** 空态页面无法证明功能跑通。
2. **不得出现真实姓名。** 本仓库公开。已逐张目视核对：界面上的用户标识为昵称 `123124` 与 UUID，无姓名。
3. **采集前确认后端健康**：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/docs` 应返回 `200`。
   端口在监听**不等于**应用层在响应——曾遇到进程僵死（端口 LISTENING 但不回包），
   当时采出的图全部是空态。

## 采集暴露并已修复的缺陷

首次采集时 `05-question-bank.png` 的**「我的题目」为空**，而接口 `/questions/batches` 实际返回
2 个批次（8 题与 13 题）。查证为真实缺陷：组件的 `loadBatches` 只挂在按钮上、没有任何程序化
调用点。已由 **ZL-144** 修复（组件挂载即加载），本图已更新为**修复后**的状态——
可见「共 8 题」与「共 13 题」两个真实批次。
