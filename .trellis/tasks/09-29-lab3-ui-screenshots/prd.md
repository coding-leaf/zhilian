# 界面截图集：开发者工具自动化抓图

> 父任务：`09-29-lab3-delivery-wrapup`，覆盖其 **R2**。
> **排期约束**：无前置任务；但本任务的清单是 `lab3-process-docs` 的输入，故宜先行。

## Goal

用微信开发者工具自动化，抓取**真实运行界面**的截图并附可核对的清单，满足老师第 1 条的
「界面截图」。明确不用 `docs/demo/index.html` 原型充数——那是原型不是产品。

## 技术路径（详见父任务 design.md 第 3 节）

`miniprogram-automator` + DevTools CLI（`D:\computerstudy\微信web开发者工具\cli.bat`），
`projectPath` 指向已有产物 `miniprogram/dist/dev/mp-weixin`，`appid: touristappid` 免登录。
工具与脚本装在**仓库外**，仓库内只放图片与清单。

## Acceptance Criteria

- [ ] AC-1 `docs/screenshots/` 含 ≥8 张真实界面截图（.png）
- [ ] AC-2 覆盖链路：登录 → 工作台/课程 → 上传 → 解析 → 出题核对 → 作答 → 判题 →
  学情/题库 → 错题本（缺失项须在 AC-4 的清单中说明原因）
- [ ] AC-3 `docs/screenshots/README.md` 标注每张图的页面、状态、在链路中的位置
- [ ] AC-4 未能覆盖的态逐一列出并写明原因（需真机 / 需手工造数据 / 需等待异步任务）
- [ ] AC-5 **逐张目视确认无真实姓名或真实用户名**（L2 钩子拦不住图片内容）
- [ ] AC-6 若自动化整体不可用，按降级方案产出拍摄清单，且**不得伪造或复用原型图**

## Out of Scope

- 不做视觉回归测试、不做像素比对。
- 不修改任何业务代码来「让截图好看」。
