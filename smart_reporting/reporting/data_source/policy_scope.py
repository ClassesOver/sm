"""将已登记口径应用于画像SQL；维度先归并，避免放大事实行。"""

from dataclasses import dataclass, field

from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import traverse_scope

from ..models import ReportingError
from ..semantics.models import Scalar, StatisticalPolicy
from ..semantics.predicates import compile_filter
from .models import CatalogTable
from .sql_validation import validate_starrocks_read_only_sql


@dataclass(frozen=True)
class ProfileScope:
    relation: exp.Expression
    parameters: dict[str, Scalar] = field(repr=False)
    checks: tuple[str, ...] = ()


def compile_profile_scope(table: CatalogTable, policy: StatisticalPolicy,
    catalog: tuple[CatalogTable, ...]) -> ProfileScope:
    tables = {(item.source_id.lower(), item.database.lower(), item.name.lower()): item for item in catalog}
    identity = (table.source_id.lower(), table.database.lower(), table.name.lower())

    def resolve(reference):
        source, database, name, column = reference.rsplit('.', 3)
        key = (source.lower(), database.lower(), name.lower())
        registered = tables.get(key)
        found = next((item for item in registered.columns if item.name.lower() == column.lower()), None) if registered else None
        if found is None:
            raise ReportingError('metric_field_denied', '画像筛选引用字段不在已登记目录中。')
        return key, found.name

    def physical(key, alias=None):
        registered = tables[key]
        return exp.Table(this=exp.to_identifier(registered.name, quoted=True),
            db=exp.to_identifier(registered.database, quoted=True),
            alias=exp.TableAlias(this=exp.to_identifier(alias)) if alias else None)

    aliases = {identity: 'f'}
    required_columns = {}
    for reference in (*[condition.field_ref for condition in policy.filters],
        *[ref for join in policy.joins for ref in (*join.left_keys, *join.right_keys)]):
        key, column = resolve(reference)
        required_columns.setdefault(key, set()).add(column)
    joins, checks, guards = [], [], []
    pending = list(policy.joins)
    while pending:
        progress = False
        for join in tuple(pending):
            left, right = tuple(resolve(ref) for ref in join.left_keys), tuple(resolve(ref) for ref in join.right_keys)
            left_key, right_key = left[0][0], right[0][0]
            if left_key not in aliases:
                continue
            if (any(key != left_key for key, _ in left) or any(key != right_key for key, _ in right)
                or right_key[:2] != identity[:2] or right_key in aliases):
                raise ReportingError('metric_join_not_supported', '画像关联须在同一连接数据库内形成无歧义路径。')
            alias = f'd{len(joins)}'
            keys = [column for _, column in right]
            duplicate = exp.select(*(exp.column(key, quoted=True) for key in keys)).from_(physical(right_key)).group_by(
                *(exp.column(key, quoted=True) for key in keys)).having(exp.GT(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(1)))
            checks.append(exp.select(exp.alias_(exp.Count(this=exp.Star()), 'violation_count')).from_(duplicate.subquery('duplicate_keys')).sql(dialect='starrocks'))
            on = exp.and_(*(exp.EQ(this=exp.column(lcol, table=aliases[left_key], quoted=True),
                expression=exp.column(rcol, table=alias, quoted=True)) for (_, lcol), (_, rcol) in zip(left, right, strict=True)))
            projections = [exp.alias_(exp.column(column.name, quoted=True) if column.name in keys else
                exp.Max(this=exp.column(column.name, quoted=True)), column.name, quoted=True)
                for column in tables[right_key].columns if column.name in required_columns.get(right_key, ())]
            projections.append(exp.alias_(exp.Count(this=exp.Star()), '_profile_matches', quoted=True))
            dimension = exp.select(*projections).from_(physical(right_key)).group_by(
                *(exp.column(key, quoted=True) for key in keys)).subquery(alias)
            joins.append((dimension, on))
            matches = exp.column('_profile_matches', table=alias, quoted=True)
            guards.append(exp.or_(exp.Is(this=matches.copy(), expression=exp.Null()),
                exp.EQ(this=matches, expression=exp.Literal.number(1))))
            aliases[right_key] = alias
            pending.remove(join)
            progress = True
        if not progress:
            break
    parameters = {}

    def parameter(value):
        name = f'p{len(parameters)}'
        parameters[name] = value
        return exp.Placeholder(this=name)

    predicates = []
    for condition in policy.filters:
        key, column = resolve(condition.field_ref)
        if key not in aliases:
            raise ReportingError('metric_filter_not_applicable', '画像筛选未映射到当前表，不能静默忽略。')
        predicates.append(compile_filter(condition, exp.column(column, table=aliases[key], quoted=True), parameter))
    predicate = exp.and_(*predicates, *guards) if predicates or guards else exp.true()
    relation = exp.select('f.*').from_(physical(identity, 'f')).where(predicate)
    for joined, on in joins:
        relation = relation.join(joined, on=on, join_type='LEFT')
    return ProfileScope(relation, parameters, tuple(checks))


class PolicyProfileAdapter:
    def __init__(self, adapter, scopes):
        self.adapter, self.scopes = adapter, scopes
        self.config, self.allowed_tables = adapter.config, adapter.allowed_tables

    async def query(self, sql):
        statement = parse_one(sql, read='starrocks')
        parameters = {}
        for table in tuple(statement.find_all(exp.Table)):
            scope = self.scopes.get((table.db.lower(), table.name.lower()))
            if scope is None:
                raise ReportingError('metric_field_denied', '画像查询超出已登记范围。')
            relation = scope.relation.copy()
            for placeholder in relation.find_all(exp.Placeholder):
                original = placeholder.name
                name = f'p{len(parameters)}'
                parameters[name] = scope.parameters[original]
                placeholder.set('this', name)
            table.replace(relation.subquery(table.alias_or_name))
        normalized = validate_starrocks_read_only_sql(statement.sql(dialect='starrocks'),
            database=self.config.database, allowed_tables=self.allowed_tables)
        return await self.adapter.query_bound(normalized, parameters)


class PolicyQueryAdapter:
    """对已审核探索SQL的每个物理表应用口径；CTE名称按SQL作用域解析。"""

    def __init__(self, adapter, *, policy: StatisticalPolicy, catalog: tuple[CatalogTable, ...]):
        self.adapter, self.policy, self.catalog = adapter, policy, catalog
        self.config, self.allowed_tables = adapter.config, adapter.allowed_tables

    def _prepare(self, sql):
        normalized = validate_starrocks_read_only_sql(sql, database=self.config.database,
            allowed_tables=self.allowed_tables)
        statement = parse_one(normalized, read='starrocks')
        if any(statement.find_all(exp.Placeholder)):
            raise ReportingError('query_parameters_invalid', '探索SQL不得自行声明服务端绑定参数。')
        registered = {(table.database.casefold(), table.name.casefold()): table
            for table in self.catalog}
        parameters, checks = {}, []
        for query_scope in traverse_scope(statement):
            for alias, (_, source) in query_scope.selected_sources.items():
                if not isinstance(source, exp.Table):
                    continue
                key = ((source.db or self.config.database).casefold(), source.name.casefold())
                table = registered.get(key)
                if table is None:
                    raise ReportingError('metric_field_denied', '探索查询引用未登记目录对象。')
                scope = compile_profile_scope(table, self.policy, self.catalog)
                checks.extend(scope.checks)
                relation = scope.relation.copy()
                for placeholder in relation.find_all(exp.Placeholder):
                    original = placeholder.name
                    name = f'p{len(parameters)}'
                    parameters[name] = scope.parameters[original]
                    placeholder.set('this', name)
                # 原database.table.column变为派生关系别名.column；不改列本身身份。
                for column in query_scope.columns:
                    if column.db and (column.db.casefold(), column.table.casefold()) == key:
                        column.set('db', None)
                        column.set('catalog', None)
                        column.set('table', exp.to_identifier(alias))
                source.replace(relation.subquery(alias))
        expanded = validate_starrocks_read_only_sql(statement.sql(dialect='starrocks'),
            database=self.config.database, allowed_tables=self.allowed_tables)
        return expanded, parameters, tuple(dict.fromkeys(checks))

    async def materialize(self, sql, *, max_bytes=None):
        expanded, parameters, checks = self._prepare(sql)

        async def verify_joins():
            for check in checks:
                result = await self.adapter.query(check)
                if result.columns != ('violation_count',) or len(result.rows) != 1 or len(result.rows[0]) != 1:
                    raise ReportingError('metric_join_check_invalid', '探索关联核对结果无效。')
                if result.rows[0][0] != 0:
                    raise ReportingError('join_fanout', '探索关联维度键不唯一，不能使用该结果。')

        await verify_joins()
        result = await self.adapter.materialize_bound(expanded, parameters, max_bytes=max_bytes)
        await verify_joins()
        return result

    async def aclose(self):
        await self.adapter.aclose()
