# 原始材料、场景与源码核对记录

日期：2026-11-09。合成试点为budget_execution；不表示正式业务签认。

- 原始行、独立Decimal oracle、2份合成材料、来源hash：见semantic_fixtures及materials.json。
- 38个case_id已登记，case执行状态仍为not_run；oracle的4项单测不是38例整体验收。
- 已清点部署目录中的旧业务Profile文件和用途，见scenario_inventory.json。文件只作调查线索，不自动转换成新规则。
- 正式制度、DDL/ETL、原始单据、已签认报表与差异裁定尚未取得；不能据此开放所有旧场景。
- 检索基准含20个有答案问题及4个无答案问题，开发/保留集分开；尚未执行真实召回测量。

## 固定源码证据

各文件身份和固定链接见semantic-source-audit/retrieved-files.json。

| 项目 | 已实际读取 | 结论与缺项 |
| --- | --- | --- |
| MetricFlow | 固定commit的Apache-2.0 LICENSE；API列出plan_conversion路径 | convert_to_sql_plan.py下载超时；计算转换及反例测试尚未完成审计 |
| Cube | 固定commit根LICENSE；API确认BaseQuery.ts真实路径 | 根声明默认Apache-2.0，部分MIT；不能替代具体包许可核对。BaseQuery.ts读取超时，fanout源码/测试审计尚未完成 |
| OpenMetadata | 固定commit的entity/data/metric.json | 195–219行分离定义/表达式/单位/粒度，243–269行包含依赖引用与元数据版本。它是元数据schema，不是确定性计算正确性的证明；服务实现/测试/许可尚缺 |
| Agno | 固定commit的pgvector.py及本地3.1.2安装源码 | vector/keyword/hybrid均先加meta_data.contains过滤再LIMIT；这是SQL构造事实，尚不是真实数据库隔离验收 |

## 本地Agno及环境探针

- 实际版本：agno3.1.2、psycopg3.3.5；pgvector Python包未安装。
- Knowledge.ainsert/asearch存在；asearch捕获多数异常后返回空列表，适配层必须额外保留故障回执，不能把所有空列表称为无匹配。
- 独立管理容器为postgres:18.0-alpine；查询pg_available_extensions证实vector扩展不可用。
- 尝试拉取pgvector/pgvector:pg18失败，Docker Registry连接超时；没有创建新向量容器。
- 因此真实ainsert/asearch、中文召回、重复写入和失败恢复均为not_run；尚未批准业务检索后端。
- 新持久化测试均使用本轮唯一semantic_test_*数据库，结束后dropdb并确认清理；没有重置预览服务或业务库。

### 后续实际探针

- 发现已缓存pgvector/pgvector:pg16镜像，创建仅本机随机端口的临时独立容器；安装pgvector Python 0.4.2用于探针，未改项目依赖清单或管理数据库。
- Agno3.1.2真实ainsert/asearch及PostgreSQL协议结果见`semantic-source-audit/agno-pgvector-protocol-probe.json`。固定非语义向量仅证明组织/集合前过滤、定位元数据保留、重复写入及embedding失败保留旧记录，不证明中文召回。
- SQL事件确认过滤在ORDER BY和LIMIT之前；8条外组织干扰记录不排挤目标组织候选。
- 实际发现Knowledge.ainsert遇到embedding失败可不抛异常；Knowledge.asearch遇到embedding或索引缺失可返回空列表。正式适配不能只靠返回值判断ready或无匹配。
- `.env`所配服务的模型列表未列出embedding模型；text-embedding-v3实际请求返回404。未改凭据、未向外发送业务原件，仅探测合成句子。中文向量召回仍not_run，不批准生产业务检索。
- 对Agno/OpenMetadata许可及Cube/MetricFlow计算源码重新定点获取仍超时或连接失败；未将其计为源码审计完成。
