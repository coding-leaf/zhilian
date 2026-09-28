"""迁移链与 ORM 模型一致性闸门。

断言「沿 Alembic 迁移链建出的 schema」与**生产模型**的表/列集合一致，
拦截「模型加了字段或表，但迁移没有对应变更、或迁移未生效」这类漂移。

背景：`tests/integration/test_p0_full_chain_e2e.py` 用 `Base.metadata.create_all()`
建表（照模型建），`tests/unit/models/test_*_migration.py` 只做单条迁移的
upgrade/downgrade 对称性 —— 两者都测不出全链漂移。2026-09-29 的登录 500
(`column users.avatar_object_key does not exist`) 正是从这个盲区漏出去的。

隔离约束：本测试**不得**经过 `migrations/env.py`。`env.py::_get_target_db_url()`
优先调用 `get_settings()`（`@lru_cache`，读 `.env` 中的真实库 URL），而
`tests/conftest.py` 的网络守卫只拦非环回地址、放行 `127.0.0.1` —— 因此调用
`alembic.command.upgrade` 会真的连上并改动开发库。迁移链改为在进程内直接回放。
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Table, create_engine, inspect
from sqlalchemy.engine import Connection, Inspector

import app.models  # noqa: F401  显式导入以注册全部模型，否则模型表集合不完整
from app.models.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

PRODUCTION_MODEL_PACKAGE = "app.models"

# 迁移运行器不会创建版本表（本测试直接调用各迁移模块的 upgrade），
# 但 Alembic 的部分路径会建；排除它以免误报为「模型未定义的表」。
_VERSION_TABLE = "alembic_version"

# {表名: 列名集合} —— 本闸门的比对数据形状。
SchemaMap = Mapping[str, set[str]]


def _script_directory() -> ScriptDirectory:
    """构造指向本仓库迁移目录的 ScriptDirectory，不依赖当前工作目录。"""
    assert ALEMBIC_INI.is_file(), f"未找到 Alembic 配置：{ALEMBIC_INI}"
    config = Config(str(ALEMBIC_INI))
    # alembic.ini 的 script_location 是 cwd 相对路径；显式替换为绝对路径，
    # 保证从 backend/ 或仓库根运行都解析到同一个迁移目录。
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(config)


def _production_model_schema() -> dict[str, set[str]]:
    """生产模型的 {表名: 列名集合}。

    必须按映射类的 `__module__` 过滤，**不能**直接读 `Base.metadata`：
    `Base` 是全局共享的，测试模块会把自己的替身模型挂上来
    （如 `tests/unit/models/test_user.py::TenantDummyItem` 注册了
    `test_tenant_items`），直接读全局 metadata 会把测试替身误判成
    「模型有表、迁移无表」。

    已知边界：未经映射类声明的裸 `Table()` 不在覆盖范围内。当前项目没有
    此类表（所有表都是 `Base` 子类映射），若将来新增需扩展本函数。
    """
    schema: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        assert isinstance(table, Table), (
            f"{mapper.class_.__qualname__} 不是单表映射，本闸门需要扩展后再覆盖"
        )
        if mapper.class_.__module__.startswith(f"{PRODUCTION_MODEL_PACKAGE}."):
            schema[table.name] = {column.name for column in table.columns}
    return schema


def _migrated_schema(inspector: Inspector) -> dict[str, set[str]]:
    """迁移链产物的 {表名: 列名集合}。"""
    return {
        name: {column["name"] for column in inspector.get_columns(name)}
        for name in inspector.get_table_names()
        if name != _VERSION_TABLE
    }


@contextmanager
def _migrated_connection() -> Iterator[Connection]:
    """在内存 SQLite 上按 base → head 回放全部迁移，产出建好 schema 的连接。"""
    import alembic.op as alembic_op
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    revisions = list(reversed(list(_script_directory().walk_revisions())))
    assert revisions, "迁移链为空，无法校验 schema 一致性"

    engine = create_engine("sqlite:///:memory:")
    sentinel = object()
    previous = getattr(alembic_op, "_proxy", sentinel)
    try:
        with engine.begin() as connection:
            alembic_op._proxy = Operations(MigrationContext.configure(connection))
            for revision in revisions:
                module = revision.module
                assert module is not None, f"迁移脚本无法加载：{revision.revision}"
                module.upgrade()
            yield connection
    finally:
        # alembic.op 的代理是模块级全局；不恢复会污染同进程后续用例
        # （既有迁移测试遗留了未恢复的 _proxy，本测试不重蹈）。
        if previous is sentinel:
            if hasattr(alembic_op, "_proxy"):
                del alembic_op._proxy
        else:
            alembic_op._proxy = previous
        engine.dispose()


def _schema_drift(model: SchemaMap, migrated: SchemaMap) -> list[str]:
    """比较模型与迁移产物的表/列名集合，返回漂移描述；空列表表示一致。

    只比较表名与列名：pgvector 列在 SQLite 会降级为 JSON、UUID 等类型存在
    方言差异，比较类型必然产生噪音；而表/列集合已精确覆盖目标故障类别。
    """
    drift: list[str] = []
    for name in sorted(set(model) - set(migrated)):
        drift.append(f"表 {name}：模型已定义，但迁移链未创建")
    for name in sorted(set(migrated) - set(model)):
        drift.append(f"表 {name}：迁移链已创建，但模型未定义")

    for name in sorted(set(model) & set(migrated)):
        for column in sorted(model[name] - migrated[name]):
            drift.append(f"表 {name} 的列 {column}：模型已定义，但迁移链未创建")
        for column in sorted(migrated[name] - model[name]):
            drift.append(f"表 {name} 的列 {column}：迁移链已创建，但模型未定义")
    return drift


def test_migration_chain_has_single_head() -> None:
    """迁移链必须收敛到单一 head。

    多 head 或断链意味着部分迁移永不生效，是漂移的另一种成因
    （典型于新增迁移时 `down_revision` 写错）。此处只断言收敛性，
    不写死具体 revision，以免每加一个迁移就要改这个测试。
    """
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"迁移链存在多个 head，存在未生效的迁移：{heads}"


def test_migrated_schema_matches_production_models() -> None:
    """迁移链产物必须与生产模型一致 —— 本闸门即拦截模型/迁移漂移。"""
    with _migrated_connection() as connection:
        drift = _schema_drift(_production_model_schema(), _migrated_schema(inspect(connection)))

    assert drift == [], "ORM 模型与 Alembic 迁移链不一致：\n" + "\n".join(drift)


def test_schema_drift_detects_injected_model_column_and_table() -> None:
    """反向验证：注入漂移必须被 `_schema_drift` 检出。

    没有这条，`_schema_drift` 退化成永真的同义反复比较也无人察觉 ——
    一个不会失败的闸门等于没有闸门。
    """
    with _migrated_connection() as connection:
        migrated = _migrated_schema(inspect(connection))

    drifted = {name: set(columns) for name, columns in _production_model_schema().items()}
    # ① 模型多出一列：2026-09-29 登录 500 的漂移形态
    drifted["users"].add("ghost_column")
    # ② 模型多出一张表
    drifted["ghost_table"] = {"id"}

    drift = _schema_drift(drifted, migrated)

    assert any("users" in item and "ghost_column" in item for item in drift), drift
    assert any("ghost_table" in item for item in drift), drift


def test_schema_drift_is_clean_for_identical_schemas() -> None:
    """守卫反向用例的可信度：集合一致时 `_schema_drift` 必须返回空。

    与上面的注入用例配对，证明该函数是「比较」而非恒定返回内容。
    """
    schema = _production_model_schema()
    assert _schema_drift(schema, {name: set(cols) for name, cols in schema.items()}) == []


def test_production_model_schema_excludes_test_only_models() -> None:
    """生产模型集合必须「既不漏、也不多」。

    多出来 = 过滤器太松（把非生产表当模型 —— 例如其它测试模块挂在全局 `Base`
    上的替身表），漏掉 = 过滤器太严（静默丢表，比太松更危险）。两个方向都断言。

    真回归场景由**全量套件**覆盖：`tests/unit/models/test_user.py` 把
    `test_tenant_items` 注册到全局 `Base`，本测试首次全量运行即因该污染失败。
    此处刻意不导入其它测试模块：全量运行时它已被 pytest 以顶层名导入过，
    再按点分路径导入会二次执行并触发
    `Table 'test_tenant_items' is already defined`。因此断言写成与当前污染
    状态无关的形式 —— 无论全局 `Base` 上挂了什么，结果都必须恰为生产映射类。
    """
    production = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.class_.__module__.startswith(f"{PRODUCTION_MODEL_PACKAGE}.")
    }
    non_production = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if not mapper.class_.__module__.startswith(f"{PRODUCTION_MODEL_PACKAGE}.")
    }

    actual = set(_production_model_schema())
    assert actual, "生产模型集合为空，过滤条件写错了"
    assert actual == production, "过滤结果与 app.models 的映射类不一致"
    assert not (actual & non_production), f"非生产表混入生产模型集合：{actual & non_production}"
