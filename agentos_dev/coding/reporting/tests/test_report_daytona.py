import csv
import hashlib
import io
import json
import os
import shlex
import textwrap
import uuid
from collections.abc import Iterable
from pathlib import Path

import pytest
from daytona import CreateSandboxFromSnapshotParams, Daytona
from pypdf import PdfReader

from agentos_dev.coding.reporting import report_runtime
from agentos_dev.workspace import (
    MAX_DOWNLOAD_BYTES,
    MAX_UPLOAD_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    WorkspaceService,
)


def _csv_bytes(rows: Iterable[Iterable[object]]) -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode()


@pytest.mark.integration
def test_sandbox_tools_复杂多轮分析后生成多页图文_pdf(tmp_path):
    if not os.getenv("DAYTONA_API_KEY"):
        pytest.skip("需要 Daytona API Key")
    client = Daytona()
    sandbox = None
    try:
        sandbox = client.create(
            CreateSandboxFromSnapshotParams(
                name=f"agui-report-integration-{uuid.uuid4().hex[:8]}",
                snapshot=WORKSPACE_SNAPSHOT,
                public=False,
                ephemeral=True,
                auto_stop_interval=60,
                auto_archive_interval=0,
                network_block_all=True,
            ),
            timeout=180,
        )
        sandbox.fs.upload_file(Path(report_runtime.__file__).read_bytes(), "/tmp/report_runtime.py")

        hospitals = ["中心医院", "城北分院", "滨江医院"]
        departments = [
            "普通外科",
            "心血内科",
            "放射科",
            "药剂科",
            "呼吸科",
            "消化内科",
            "神经内科",
            "骨科",
            "妇产科",
            "儿科",
            "急诊科",
            "重症医学科",
            "检验科",
            "超声科",
            "病理科",
            "麻醉科",
            "肿瘤科",
            "康复科",
            "眼科",
            "耳鼻喉科",
        ]

        def employee_rows():
            yield ["员工编号", "医院", "科室", "岗位", "月薪", "司龄年", "年龄"]
            for index in range(80_000):
                yield [
                    f"E{index + 1:06d}",
                    hospitals[index % len(hospitals)],
                    departments[index * 7 % len(departments)],
                    ("医师", "护士", "技师", "主管")[index % 4],
                    8_500 + index % 80 * 125,
                    round(0.5 + index % 30 * 0.5, 1),
                    22 + index % 39,
                ]

        def revenue_rows():
            yield ["日期", "医院", "科室", "收入类别", "收入", "成本", "就诊量"]
            for index in range(120_000):
                month_index = index % 36
                yield [
                    f"{2023 + month_index // 12}-{month_index % 12 + 1:02d}-{index % 28 + 1:02d}",
                    hospitals[index * 5 % len(hospitals)],
                    departments[index * 11 % len(departments)],
                    ("门诊", "住院", "检查", "药品")[index % 4],
                    5_000 + index % 97 * 125,
                    2_800 + index % 71 * 90,
                    20 + index % 180,
                ]

        turnover_rows = [["月份", "医院", "科室", "离职人数"]]
        for month_index in range(36):
            for hospital_index, hospital in enumerate(hospitals):
                for department_index, department in enumerate(departments):
                    turnover_rows.append(
                        [
                            f"{2023 + month_index // 12}-{month_index % 12 + 1:02d}",
                            hospital,
                            department,
                            (month_index + hospital_index + department_index * 2) % 8,
                        ]
                    )

        employees_csv = _csv_bytes(employee_rows())
        revenue_csv = _csv_bytes(revenue_rows())
        turnover_csv = _csv_bytes(turnover_rows)
        assert 4 * 1024 * 1024 < len(employees_csv) <= MAX_UPLOAD_BYTES
        assert 6 * 1024 * 1024 < len(revenue_csv) <= MAX_UPLOAD_BYTES
        sandbox.fs.upload_file(employees_csv, f"{WORKSPACE_ROOT}/employees.csv")
        sandbox.fs.upload_file(revenue_csv, f"{WORKSPACE_ROOT}/revenue.csv")
        sandbox.fs.upload_file(turnover_csv, f"{WORKSPACE_ROOT}/turnover.csv")

        def run(action, payload):
            command = (
                f"python /tmp/report_runtime.py {shlex.quote(action)} "
                f"{shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            )
            result = sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=600)
            assert result.exit_code == 0, result.result
            output = next(line for line in reversed(result.result.splitlines()) if line.strip())
            return json.loads(output)

        def analyze(source: str):
            command = "python - <<'PY'\n" + textwrap.dedent(source).strip() + "\nPY"
            result = sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=120)
            return {
                "ok": result.exit_code == 0,
                "exitCode": result.exit_code,
                "output": result.result,
            }

        job_id = str(uuid.uuid4())
        job = {
            "jobId": job_id,
            "sources": [
                {
                    "path": path,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for path, content in (
                    ("employees.csv", employees_csv),
                    ("revenue.csv", revenue_csv),
                    ("turnover.csv", turnover_csv),
                )
            ],
        }
        failed_process = sandbox.process.exec(
            "python -c 'raise ValueError(\"缺少预期分析列\")'",
            cwd=WORKSPACE_ROOT,
            timeout=120,
        )
        failed = {
            "ok": failed_process.exit_code == 0,
            "exitCode": failed_process.exit_code,
            "output": failed_process.result,
        }
        assert failed["ok"] is False
        assert failed["exitCode"] != 0
        assert "Traceback" in failed["output"]

        directory = f"报表/生成结果/{job_id}"
        summarized = analyze(
            f"""
            import json
            from pathlib import Path
            import pandas as pd

            employees = pd.read_csv("employees.csv")
            required = {{"员工编号", "医院", "科室", "岗位", "月薪", "司龄年", "年龄"}}
            assert required.issubset(employees.columns)
            output = Path({directory!r})
            output.mkdir(parents=True, exist_ok=True)
            summary = employees.groupby(["医院", "科室"], as_index=False).agg(
                员工数=("员工编号", "count"),
                平均月薪=("月薪", "mean"),
                平均司龄=("司龄年", "mean"),
            )
            summary["平均月薪"] = summary["平均月薪"].round(2)
            summary["平均司龄"] = summary["平均司龄"].round(2)
            summary.to_csv(output / "人员汇总.csv", index=False)
            metrics = {{
                "employeeCount": int(len(employees)),
                "hospitalCount": int(employees["医院"].nunique()),
                "departmentCount": int(employees["科室"].nunique()),
                "averageSalary": round(float(employees["月薪"].mean()), 2),
            }}
            (output / "基础指标.json").write_text(
                json.dumps(metrics, ensure_ascii=False), encoding="utf-8"
            )
            print(json.dumps(metrics, ensure_ascii=False))
            """,
        )
        assert summarized["ok"] is True
        assert '"employeeCount": 80000' in summarized["output"]

        trended = analyze(
            f"""
            import json
            from pathlib import Path
            import pandas as pd

            root = Path({directory!r})
            employees = pd.read_csv("employees.csv")
            revenue = pd.read_csv("revenue.csv", parse_dates=["日期"])
            turnover = pd.read_csv("turnover.csv")
            revenue["月份"] = revenue["日期"].dt.to_period("M").astype(str)
            monthly_finance = revenue.groupby("月份", as_index=False).agg(
                收入=("收入", "sum"), 成本=("成本", "sum"), 就诊量=("就诊量", "sum")
            )
            monthly_finance["结余"] = monthly_finance["收入"] - monthly_finance["成本"]
            monthly_finance["结余率"] = (
                monthly_finance["结余"] / monthly_finance["收入"] * 100
            ).round(2)
            monthly_finance.to_csv(root / "月度经营趋势.csv", index=False)

            headcount = employees.groupby(["医院", "科室"]).size().rename("员工数")
            finance = revenue.groupby(["医院", "科室"]).agg(
                收入=("收入", "sum"), 成本=("成本", "sum"), 就诊量=("就诊量", "sum")
            )
            departures = turnover.groupby(["医院", "科室"])["离职人数"].sum()
            operations = pd.concat([headcount, finance, departures], axis=1).fillna(0).reset_index()
            operations["人均收入"] = (operations["收入"] / operations["员工数"]).round(2)
            operations["结余率"] = (
                (operations["收入"] - operations["成本"]) / operations["收入"] * 100
            ).round(2)
            operations["三年离职率"] = (
                operations["离职人数"] / operations["员工数"] * 100
            ).round(2)
            operations.to_csv(root / "科室经营与人员风险.csv", index=False)

            monthly_turnover = turnover.groupby("月份", as_index=False)["离职人数"].sum()
            monthly_turnover.to_csv(root / "月度离职趋势.csv", index=False)
            highest_risk = operations.sort_values("三年离职率", ascending=False).iloc[0]
            result = {{
                "revenueRowCount": int(len(revenue)),
                "totalRevenue": int(revenue["收入"].sum()),
                "totalMargin": round(
                    float((revenue["收入"].sum() - revenue["成本"].sum()) / revenue["收入"].sum() * 100),
                    2,
                ),
                "threeYearDepartures": int(turnover["离职人数"].sum()),
                "peakTurnoverMonth": str(
                    monthly_turnover.loc[monthly_turnover["离职人数"].idxmax(), "月份"]
                ),
                "highestRiskDepartment": str(highest_risk["科室"]),
            }}
            (root / "趋势指标.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            print(json.dumps(result, ensure_ascii=False))
            """,
        )
        assert trended["ok"] is True
        assert '"revenueRowCount": 120000' in trended["output"]

        reported = analyze(
            f"""
            import json
            from pathlib import Path
            import matplotlib.pyplot as plt
            import pandas as pd

            root = Path({directory!r})
            assets = root / "assets"
            assets.mkdir(exist_ok=True)
            employees = pd.read_csv("employees.csv")
            summary = pd.read_csv(root / "人员汇总.csv")
            monthly_finance = pd.read_csv(root / "月度经营趋势.csv")
            monthly_turnover = pd.read_csv(root / "月度离职趋势.csv")
            operations = pd.read_csv(root / "科室经营与人员风险.csv")
            metrics = json.loads((root / "基础指标.json").read_text(encoding="utf-8"))
            trends = json.loads((root / "趋势指标.json").read_text(encoding="utf-8"))

            hospital = employees.groupby("医院").size()
            hospital.plot(kind="bar", color=["#2563eb", "#16a34a", "#d97706"], figsize=(7, 3))
            plt.title("各医院员工人数")
            plt.ylabel("员工数")
            plt.tight_layout()
            plt.savefig(assets / "hospital.png", dpi=120)
            plt.close()

            department = employees.groupby("科室").size().sort_values(ascending=False)
            department.plot(kind="bar", color="#0f766e", figsize=(7, 3))
            plt.title("各科室员工人数")
            plt.ylabel("员工数")
            plt.tight_layout()
            plt.savefig(assets / "department.png", dpi=120)
            plt.close()

            monthly_finance.plot(
                x="月份", y=["收入", "成本"], color=["#2563eb", "#dc2626"], figsize=(7, 3)
            )
            plt.title("月度收入与成本趋势")
            plt.ylabel("金额")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(assets / "finance.png", dpi=120)
            plt.close()

            monthly_turnover.plot(
                x="月份", y="离职人数", marker="o", color="#dc2626", figsize=(7, 3)
            )
            plt.title("月度离职趋势")
            plt.ylabel("离职人数")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(assets / "turnover.png", dpi=120)
            plt.close()

            def table(frame):
                header = "| " + " | ".join(frame.columns) + " |"
                separator = "| " + " | ".join("---" for _ in frame.columns) + " |"
                rows = [
                    "| " + " | ".join(str(value) for value in row) + " |"
                    for row in frame.itertuples(index=False, name=None)
                ]
                return "\\n".join([header, separator, *rows])

            hospital_table = hospital.rename("员工数").reset_index()
            department_table = department.rename("员工数").reset_index()
            operations_view = operations.sort_values("收入", ascending=False).head(20)
            report = "\\n\\n".join([
                "# 医院经营与人力资源综合分析报告",
                "## 一、执行摘要",
                f"本报告联合分析三家医院 {{metrics['employeeCount']}} 条员工明细、{{trends['revenueRowCount']}} 条收入成本明细以及连续 36 个月离职数据，完成组织规模、收入结构、成本结余、服务负荷和人员风险分析。数据覆盖 {{metrics['departmentCount']}} 个科室，全部指标均由源 CSV 和前序分析产物确定性计算。",
                f"| 核心指标 | 结果 |\\n| --- | ---: |\\n| 员工总数 | {{metrics['employeeCount']}} 人 |\\n| 医院数量 | {{metrics['hospitalCount']}} 家 |\\n| 科室数量 | {{metrics['departmentCount']}} 个 |\\n| 累计收入 | {{trends['totalRevenue']}} 元 |\\n| 综合结余率 | {{trends['totalMargin']}}% |\\n| 三年离职人数 | {{trends['threeYearDepartures']}} 人 |",
                "## 二、医院人员分布",
                table(hospital_table),
                "三家医院人员规模接近，但收入、成本和就诊量仍需结合院区功能定位解释。后续编制调整应同时参考业务量、床位数和门急诊量，不能仅凭人数作出扩编或缩编结论。",
                "![医院人员分布](assets/hospital.png)",
                "## 三、科室人员结构",
                table(department_table),
                "普通外科是当前人员规模最大的科室。不同科室的岗位结构和服务强度不同，人数排名适合用于发现进一步分析方向，不应替代专业的人力配置标准。",
                "![科室人员分布](assets/department.png)",
                "## 四、薪酬与司龄概览",
                table(summary[["医院", "科室", "员工数", "平均月薪", "平均司龄"]]),
                "薪酬分析展示各医院科室的平均水平，便于发现结构差异。平均值可能掩盖岗位、职级和资历差异，正式决策前应继续检查分位数、岗位序列以及同岗薪酬离散度。",
                "## 五、收入、成本与服务负荷",
                f"36 个月累计收入为 {{trends['totalRevenue']}} 元，综合结余率为 {{trends['totalMargin']}}%。收入与成本趋势用于识别经营波动，就诊量用于辅助解释变化，三者不能相互替代。",
                table(monthly_finance),
                "![月度收入成本趋势](assets/finance.png)",
                "## 六、跨表科室经营分析",
                "下表将科室收入、成本、就诊量与员工人数连接，计算人均收入、结余率和三年离职率。为控制报告篇幅，仅展示收入最高的二十个院区科室组合，完整结果保留在 CSV 产物中。",
                table(operations_view),
                "## 七、年度离职趋势",
                f"三年离职记录合计 {{trends['threeYearDepartures']}} 人，峰值月份为 {{trends['peakTurnoverMonth']}}。月度变化可用于安排招聘和培训窗口，但还需结合内部调动、退休和主动离职原因复核。",
                table(monthly_turnover),
                "![月度离职趋势](assets/turnover.png)",
                "## 八、科室离职风险",
                table(operations_view[["医院", "科室", "员工数", "人均收入", "结余率", "三年离职率"]]),
                f"按三年离职人数与当前员工数的比值估算，最高风险科室为 {{trends['highestRiskDepartment']}}。该指标用于筛查异常，不代表严格的人员流失率，因为当前员工数并非逐月平均在岗人数。",
                "## 九、数据质量与方法边界",
                "人员主数据的员工编号完整，收入明细覆盖 36 个月，离职数据覆盖全部院区科室。本报告保留三个大型源文件不变，分析阶段只写入任务结果目录。收入和成本为测试口径，尚未包含应收账款、折旧和资金时间价值。",
                "## 十、管理建议",
                "第一，针对高风险科室开展岗位和司龄分层访谈，识别离职集中发生的具体人群。第二，将月度业务量与排班强度加入后续模型，评估人员规模是否匹配服务需求。第三，建立同口径的季度跟踪表，连续观察招聘、离职和内部调动，避免用单期结果替代趋势判断。",
                "## 十一、结论",
                "本次多轮分析完成了大型源数据校验、跨表聚合、收入成本趋势计算、人员风险排序和图文报告生成。报告中的 80000 人总量、120000 条收入明细、科室排名及离职指标均可从工作区产物复核。",
            ])
            (root / "复杂人力资源分析报告.md").write_text(report, encoding="utf-8")
            print(json.dumps({{"markdown": str(root / "复杂人力资源分析报告.md"), "charts": 4}}, ensure_ascii=False))
            """,
        )
        assert reported["ok"] is True, reported["output"]
        assert '"charts": 4' in reported["output"]
        assert "Glyph" not in reported["output"]

        temporary_pdf = f"/tmp/workspace-report-{uuid.uuid4().hex}-render/render.pdf"
        rendered = run(
            "render_markdown",
            {
                "job": job,
                "markdown_path": f"{directory}/复杂人力资源分析报告.md",
                "output_path": f"{directory}/复杂人力资源分析报告.pdf",
                "temporary_path": temporary_pdf,
            },
        )
        render = rendered.pop("render")
        sandbox.process.exec(
            f"cp --no-clobber -- {shlex.quote(temporary_pdf)} "
            f"{shlex.quote(WORKSPACE_ROOT + '/' + rendered['pdfPath'])}",
            cwd=WORKSPACE_ROOT,
            timeout=30,
        )
        job["render"] = render
        assert rendered["imageCount"] == 4
        assert rendered["pageCount"] >= 2
        assert rendered["size"] > 20_000

        validated = run(
            "validate_pdf",
            {
                "job": job,
                "pdf_path": rendered["pdfPath"],
                "temporary_directory": f"/tmp/workspace-report-{uuid.uuid4().hex}-validate",
            },
        )
        assert validated["ok"] is True
        assert validated["status"] == "validated"
        assert validated["blankPages"] == []
        assert validated["missingImageCount"] == 0

        content = WorkspaceService._download_file(
            sandbox,
            f"{WORKSPACE_ROOT}/{rendered['pdfPath']}",
            MAX_DOWNLOAD_BYTES,
        )
        download_path = Path(
            os.getenv("REPORT_INTEGRATION_OUTPUT", tmp_path / "医院经营与人力资源综合分析报告.pdf")
        )
        download_path.write_bytes(content)
        assert download_path.stat().st_size == rendered["size"]
        reader = PdfReader(io.BytesIO(content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        assert len(reader.pages) == rendered["pageCount"]
        assert "医院经营与人力资源综合分析报告" in text
        assert "年度离职趋势" in text
        assert "数据质量与方法边界" in text
        assert "80000" in text
        assert "普通外科" in text
        assert sum(len(page.images) for page in reader.pages) >= 4
    finally:
        if sandbox is not None:
            client.delete(sandbox)
