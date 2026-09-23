import shutil
import tempfile
import unittest
from pathlib import Path

from tooling.task_cli import TaskManager


class TestTaskManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

        # 拷贝真实模板目录到测试沙箱以支持端到端物化测试
        src_tpl = Path(__file__).resolve().parent.parent / "docs" / "sdlc" / "_template"
        dst_tpl = self.root / "docs" / "sdlc" / "_template"
        dst_tpl.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_tpl, dst_tpl)

        self.mgr = TaskManager(workspace_root=self.root)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_init_and_empty_list(self):
        tasks = self.mgr.parse_active_tasks()
        self.assertEqual(len(tasks), 0)
        self.assertTrue(self.mgr.check())

    def test_create_tier1_task(self):
        # Tier 1 属于轻量任务，无需生成前置工件
        self.mgr.create("quick-patch", title="快速修复", tier=1, stage="Plan")
        tasks = self.mgr.parse_active_tasks()
        self.assertIn("quick-patch", tasks)
        self.assertEqual(tasks["quick-patch"].risk, "Tier 1")
        self.assertEqual(tasks["quick-patch"].sdlc_path, "None")
        self.assertFalse((self.mgr.sdlc_dir / "quick-patch").exists())

    def test_create_tier2_lifecycle_and_rollback(self):
        task_id = "test-feature"
        # 1. 创建 Tier 2 任务 (默认 Plan 阶段，仅释放 intent.md)
        self.mgr.create(task_id, title="测试特性", tier=2, stage="Plan")
        artifact_dir = self.mgr.sdlc_dir / task_id
        self.assertTrue((artifact_dir / "intent.md").exists())
        self.assertFalse((artifact_dir / "spec.md").exists())
        self.assertFalse((artifact_dir / "plan.md").exists())

        # 2. 推进到 Design 阶段，释放 spec.md
        self.mgr.update(task_id, stage="Design")
        self.assertTrue((artifact_dir / "spec.md").exists())
        self.assertFalse((artifact_dir / "plan.md").exists())

        # 3. 推进到 Build 阶段，释放 plan.md
        self.mgr.update(task_id, stage="Build")
        self.assertTrue((artifact_dir / "plan.md").exists())

        # 4. 阶段回退到 Plan，应触发 .bak 安全备份保护，解除防偷跑门禁自锁
        self.mgr.update(task_id, stage="Plan")
        tasks = self.mgr.parse_active_tasks()
        self.assertEqual(tasks[task_id].stage, "Plan")
        self.assertFalse((artifact_dir / "spec.md").exists())
        self.assertFalse((artifact_dir / "plan.md").exists())
        self.assertTrue((artifact_dir / "spec.md.bak").exists())
        self.assertTrue((artifact_dir / "plan.md.bak").exists())

        # 5. 重新向前推进到 Design，应从 .bak 恢复工件
        self.mgr.update(task_id, stage="Design")
        self.assertTrue((artifact_dir / "spec.md").exists())
        self.assertFalse((artifact_dir / "spec.md.bak").exists())

    def test_anti_leapfrog_check(self):
        task_id = "leapfrog-task"
        self.mgr.create(task_id, title="防跳步测试", tier=2, stage="Plan")
        artifact_dir = self.mgr.sdlc_dir / task_id

        # 在 Plan 阶段如果强行放置 spec.md，应当被 check() 门禁识别拦截
        (artifact_dir / "spec.md").write_text("提前偷跑的 spec", encoding="utf-8")
        passed = self.mgr.check(task_id)
        self.assertFalse(passed)

    def test_archive_workflow(self):
        task_id = "done-task"
        self.mgr.create(task_id, title="已完成任务", tier=2, stage="Plan")
        self.assertIn(task_id, self.mgr.parse_active_tasks())

        # 归档操作
        self.mgr.archive(
            task_id,
            outcome="完整实现并通过全部测试",
            commit_pr="c0ffee1",
            verification="10 tests passed",
            final_stage="Deploy",
        )

        # 验证从 active 中移除，并写入 ARCHIVE.md
        self.assertNotIn(task_id, self.mgr.parse_active_tasks())
        archive_content = self.mgr.archive_file.read_text(encoding="utf-8")
        self.assertIn(task_id, archive_content)
        self.assertIn("c0ffee1", archive_content)


if __name__ == "__main__":
    unittest.main()
