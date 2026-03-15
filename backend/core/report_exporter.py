"""
Ghost Protocol — Report Export Utilities

Builds downloadable JSON and PDF exports from the canonical match state and
post-game report without relying on external PDF libraries.
"""
from __future__ import annotations

import json
import textwrap
from typing import Literal

from pydantic import BaseModel, Field

from backend.core.match_state import MatchState, utc_now
from backend.core.report_generator import MatchReport

ExportFormat = Literal["json", "pdf"]


class ReportExportBundle(BaseModel):
    exported_at: str = Field(default_factory=utc_now)
    format: ExportFormat
    match: MatchState
    report: MatchReport
    report_text: str


class ReportExporter:
    _page_width = 595
    _page_height = 842
    _left_margin = 48
    _top_margin = 792
    _bottom_margin = 52

    def build_bundle(
        self,
        match_state: MatchState,
        report: MatchReport,
        export_format: ExportFormat,
    ) -> ReportExportBundle:
        return ReportExportBundle(
            format=export_format,
            match=match_state,
            report=report,
            report_text=self.render_report_text(match_state, report),
        )

    def build_json_export(self, match_state: MatchState, report: MatchReport) -> bytes:
        bundle = self.build_bundle(match_state, report, "json")
        payload = bundle.model_dump(mode="json")
        return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

    def build_pdf_export(self, match_state: MatchState, report: MatchReport) -> bytes:
        elements = self._build_pdf_elements(match_state, report)
        pages = self._paginate_elements(elements)
        return self._build_pdf_document(pages)

    def build_download_filename(self, match_id: str, export_format: ExportFormat) -> str:
        return f"ghost-protocol-report-{match_id}.{export_format}"

    def render_report_text(self, match_state: MatchState, report: MatchReport) -> str:
        lines: list[str] = [
            "Ghost Protocol Post-Game Report",
            "================================",
            "",
            f"Match ID: {match_state.match_id}",
            f"Report ID: {report.report_id}",
            f"Scenario: {report.scenario_name}",
            f"Attacker Persona: {(report.criminal_persona or 'unknown').title()}",
            f"Generated At: {report.generated_at}",
            f"Runtime Mode: {report.runtime_mode}",
            f"Share URL: {match_state.share_url or 'unavailable'}",
            f"Rounds Completed: {report.rounds_completed}/{report.total_rounds}",
            "",
            "Final Score",
            "-----------",
            f"Caught: {report.caught}",
            f"Missed: {report.missed}",
            f"False Alarms: {report.final_score.false_positives}",
            f"Legit Approved: {report.final_score.true_negatives}",
            f"Precision: {report.final_score.precision:.2f}",
            f"Recall: {report.final_score.recall:.2f}",
            f"F1 Score: {report.final_score.f1_score:.2f}",
            f"Money Defended: ${report.money_defended:.2f}",
            f"Money Lost: ${report.money_lost:.2f}",
            f"Risk Rating: {report.risk_rating}",
            "",
            "Executive Summary",
            "-----------------",
            report.executive_summary,
            "",
            "Critical Vulnerabilities",
            "------------------------",
        ]

        if report.critical_vulnerabilities:
            lines.extend(f"- {item}" for item in report.critical_vulnerabilities)
        else:
            lines.append("- No critical vulnerabilities were identified.")

        lines.extend(
            [
                "",
                "Attack Pattern Analysis",
                "-----------------------",
                report.attack_pattern_analysis,
                "",
                "Security Gaps",
                "-------------",
            ]
        )

        if report.security_gaps:
            for index, gap in enumerate(report.security_gaps, start=1):
                lines.extend(
                    [
                        f"{index}. {gap.pattern_name}",
                        f"   Category: {gap.category}",
                        f"   Transactions Exploited: {gap.transactions_exploited}",
                        f"   Money Slipped Through: ${gap.total_money_slipped_through:.2f}",
                        (
                            "   Example: "
                            f"{gap.example_transaction.amount:.2f} {gap.example_transaction.currency} at "
                            f"{gap.example_transaction.merchant_label}, "
                            f"{gap.example_transaction.location}, "
                            f"{gap.example_transaction.time_window}"
                        ),
                    ]
                )
        else:
            lines.append("No security gaps were identified.")

        lines.extend(["", "Recommendations", "---------------"])
        if report.recommendations:
            for index, recommendation in enumerate(report.recommendations, start=1):
                lines.extend(
                    [
                        f"{index}. [{recommendation.priority}] {recommendation.title}",
                        f"   Action: {recommendation.action}",
                        f"   Rationale: {recommendation.rationale}",
                    ]
                )
                if recommendation.code_hint:
                    lines.append(f"   Code Hint: {recommendation.code_hint}")
        else:
            lines.append("No recommendations were generated.")

        return "\n".join(lines).strip()

    def _build_pdf_elements(
        self,
        match_state: MatchState,
        report: MatchReport,
    ) -> list[tuple[int, str]]:
        elements: list[tuple[int, str]] = []

        self._append_pdf_line(elements, 18, "Ghost Protocol Post-Game Report")
        self._append_pdf_line(elements, 11, f"Match ID: {match_state.match_id}")
        self._append_pdf_line(elements, 11, f"Report ID: {report.report_id}")
        self._append_pdf_line(elements, 11, f"Scenario: {report.scenario_name}")
        self._append_pdf_line(
            elements,
            11,
            f"Attacker Persona: {(report.criminal_persona or 'unknown').title()}",
        )
        self._append_pdf_line(elements, 11, f"Generated At: {report.generated_at}")
        self._append_pdf_line(elements, 11, f"Runtime Mode: {report.runtime_mode}")
        self._append_pdf_line(
            elements,
            11,
            f"Rounds Completed: {report.rounds_completed}/{report.total_rounds}",
        )
        self._append_pdf_line(
            elements,
            11,
            f"Share URL: {match_state.share_url or 'unavailable'}",
        )
        self._append_pdf_blank_line(elements)

        self._append_pdf_heading(elements, "Final Score")
        for label, value in [
            ("Caught", str(report.caught)),
            ("Missed", str(report.missed)),
            ("False Alarms", str(report.final_score.false_positives)),
            ("Legit Approved", str(report.final_score.true_negatives)),
            ("Precision", f"{report.final_score.precision:.2f}"),
            ("Recall", f"{report.final_score.recall:.2f}"),
            ("F1 Score", f"{report.final_score.f1_score:.2f}"),
            ("Money Defended", f"${report.money_defended:.2f}"),
            ("Money Lost", f"${report.money_lost:.2f}"),
            ("Risk Rating", report.risk_rating),
        ]:
            self._append_pdf_line(elements, 11, f"{label}: {value}")

        self._append_pdf_heading(elements, "Executive Summary")
        self._append_wrapped_pdf_text(elements, 11, report.executive_summary)

        self._append_pdf_heading(elements, "Critical Vulnerabilities")
        if report.critical_vulnerabilities:
            for item in report.critical_vulnerabilities:
                self._append_wrapped_pdf_text(elements, 11, item, prefix="- ", hanging="  ")
        else:
            self._append_wrapped_pdf_text(
                elements,
                11,
                "No critical vulnerabilities were identified.",
            )

        self._append_pdf_heading(elements, "Attack Pattern Analysis")
        self._append_wrapped_pdf_text(elements, 11, report.attack_pattern_analysis)

        self._append_pdf_heading(elements, "Security Gaps")
        if report.security_gaps:
            for index, gap in enumerate(report.security_gaps, start=1):
                self._append_wrapped_pdf_text(elements, 12, f"{index}. {gap.pattern_name}")
                self._append_wrapped_pdf_text(elements, 11, f"Category: {gap.category}")
                self._append_wrapped_pdf_text(
                    elements,
                    11,
                    f"Transactions Exploited: {gap.transactions_exploited}",
                )
                self._append_wrapped_pdf_text(
                    elements,
                    11,
                    f"Money Slipped Through: ${gap.total_money_slipped_through:.2f}",
                )
                self._append_wrapped_pdf_text(
                    elements,
                    11,
                    (
                        "Example: "
                        f"{gap.example_transaction.amount:.2f} {gap.example_transaction.currency} at "
                        f"{gap.example_transaction.merchant_label}, "
                        f"{gap.example_transaction.location}, "
                        f"{gap.example_transaction.time_window}"
                    ),
                )
        else:
            self._append_wrapped_pdf_text(elements, 11, "No security gaps were identified.")

        self._append_pdf_heading(elements, "Recommendations")
        if report.recommendations:
            for index, recommendation in enumerate(report.recommendations, start=1):
                self._append_wrapped_pdf_text(
                    elements,
                    12,
                    f"{index}. [{recommendation.priority}] {recommendation.title}",
                )
                self._append_wrapped_pdf_text(
                    elements,
                    11,
                    f"Action: {recommendation.action}",
                )
                self._append_wrapped_pdf_text(
                    elements,
                    11,
                    f"Rationale: {recommendation.rationale}",
                )
                if recommendation.code_hint:
                    self._append_wrapped_pdf_text(
                        elements,
                        11,
                        f"Code Hint: {recommendation.code_hint}",
                    )
        else:
            self._append_wrapped_pdf_text(elements, 11, "No recommendations were generated.")

        return elements

    def _append_pdf_heading(self, elements: list[tuple[int, str]], text: str) -> None:
        self._append_pdf_blank_line(elements)
        self._append_pdf_line(elements, 14, text)

    def _append_pdf_blank_line(self, elements: list[tuple[int, str]]) -> None:
        elements.append((8, ""))

    def _append_pdf_line(self, elements: list[tuple[int, str]], size: int, text: str) -> None:
        elements.append((size, text))

    def _append_wrapped_pdf_text(
        self,
        elements: list[tuple[int, str]],
        size: int,
        text: str,
        *,
        prefix: str = "",
        hanging: str | None = None,
    ) -> None:
        if not text.strip():
            self._append_pdf_blank_line(elements)
            return

        wrapped = textwrap.wrap(
            text.strip(),
            width=self._wrap_width_for_size(size),
            initial_indent=prefix,
            subsequent_indent=hanging if hanging is not None else " " * len(prefix),
            break_long_words=True,
            break_on_hyphens=False,
        )
        for line in wrapped:
            self._append_pdf_line(elements, size, line)

    def _wrap_width_for_size(self, size: int) -> int:
        if size >= 18:
            return 52
        if size >= 14:
            return 70
        if size >= 12:
            return 82
        return 92

    def _paginate_elements(self, elements: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
        pages: list[list[tuple[int, str]]] = []
        current_page: list[tuple[int, str]] = []
        current_y = self._top_margin

        for size, text in elements:
            line_height = size + 4
            if current_y - line_height < self._bottom_margin and current_page:
                pages.append(current_page)
                current_page = []
                current_y = self._top_margin

            current_page.append((size, text))
            current_y -= line_height

        if current_page:
            pages.append(current_page)

        return pages or [[(18, "Ghost Protocol Post-Game Report")]]

    def _build_pdf_document(self, pages: list[list[tuple[int, str]]]) -> bytes:
        objects: dict[int, bytes] = {
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n",
        }
        page_ids: list[int] = []
        next_object_id = 4

        for page in pages:
            page_id = next_object_id
            content_id = next_object_id + 1
            next_object_id += 2
            page_ids.append(page_id)

            content_stream = self._build_page_stream(page)
            objects[page_id] = (
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {self._page_width} {self._page_height}] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {content_id} 0 R >>\n"
            ).encode("ascii")
            objects[content_id] = (
                f"<< /Length {len(content_stream)} >>\nstream\n".encode("ascii")
                + content_stream
                + b"\nendstream\n"
            )

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>\n"
        objects[2] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>\n".encode("ascii")

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = [0]
        max_object_id = max(objects)

        for object_id in range(1, max_object_id + 1):
            object_bytes = objects[object_id]
            offsets.append(len(output))
            output.extend(f"{object_id} 0 obj\n".encode("ascii"))
            output.extend(object_bytes)
            if not object_bytes.endswith(b"\n"):
                output.extend(b"\n")
            output.extend(b"endobj\n")

        startxref = len(output)
        output.extend(f"xref\n0 {max_object_id + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for object_id in range(1, max_object_id + 1):
            output.extend(f"{offsets[object_id]:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {max_object_id + 1} /Root 1 0 R >>\n"
                f"startxref\n{startxref}\n%%EOF"
            ).encode("ascii")
        )
        return bytes(output)

    def _build_page_stream(self, page: list[tuple[int, str]]) -> bytes:
        commands: list[str] = []
        current_y = self._top_margin

        for size, text in page:
            line_height = size + 4
            if text:
                commands.append(
                    f"BT /F1 {size} Tf {self._left_margin} {current_y} Td "
                    f"({self._escape_pdf_text(text)}) Tj ET"
                )
            current_y -= line_height

        return "\n".join(commands).encode("latin-1", "replace")

    def _escape_pdf_text(self, value: str) -> str:
        normalized = value.encode("latin-1", "replace").decode("latin-1")
        normalized = normalized.replace("\\", "\\\\")
        normalized = normalized.replace("(", "\\(")
        normalized = normalized.replace(")", "\\)")
        return normalized.replace("\r", " ").replace("\n", " ")


REPORT_EXPORTER = ReportExporter()
