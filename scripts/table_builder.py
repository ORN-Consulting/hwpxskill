#!/usr/bin/env python3
"""
table_builder.py — HWPX 표 XML 생성 헬퍼

셀 하나당 수십 줄의 반복 XML을 생성하는 작업을 함수 호출로 대체.
Claude가 데이터만 넘기면 올바른 HWPX 표 XML이 생성된다.

사용법:
    from table_builder import TableBuilder

    # 기본 사용 (report 템플릿 기준)
    tb = TableBuilder(col_widths=[14173, 14173, 14174])
    tb.header_row(["부서", "매출", "증감"])
    tb.data_row(["영업부", "125억", "+12%"])
    tb.data_row(["마케팅부", "89억", "+5%"])
    xml = tb.build(table_id=1000000099)

    # 표 너비 합산 검증
    assert sum([14173, 14173, 14174]) == 42520  # A4 본문폭

    # 셀 병합 (colSpan/rowSpan)
    tb = TableBuilder(col_widths=[10000, 16260, 16260])
    tb.add_row([
        Cell("항목", col_span=1),
        Cell("Q1", col_span=1),
        Cell("Q2", col_span=1),
    ], is_header=True)
    tb.add_row([
        Cell("합계", row_span=2),   # 아래 행과 병합
        Cell("100"),
        Cell("120"),
    ])

CLI 사용:
    python table_builder.py --demo
    python table_builder.py --demo-merge
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# 상수: 기본 borderFill ID (report 템플릿 기준)
# ──────────────────────────────────────────────────────────────────────────────
BORDER_HEADER = 4   # SOLID 0.12mm + 배경색 (#DAEEF3)
BORDER_DATA = 3     # SOLID 0.12mm 4면, 배경 없음
BORDER_TABLE = 3    # 표 기본 테두리

# 기본 paraPr / charPr ID (report 템플릿)
PARA_CENTER = 21    # CENTER, 130% 줄간격 (표 셀 기본)
PARA_JUSTIFY = 22   # JUSTIFY, 130% 줄간격
CHAR_HEADER = 9     # 10pt 볼드 (표 헤더)
CHAR_NORMAL = 0     # 10pt 기본

# A4 기본
A4_CONTENT_WIDTH = 42520  # HWPUNIT
DEFAULT_ROW_HEIGHT = 2800  # HWPUNIT

# XML 네임스페이스 (section0.xml 내부에서는 접두사만 사용)
_XMLNS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"'
)


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Cell:
    """단일 셀 데이터."""
    text: str = ""
    col_span: int = 1
    row_span: int = 1
    # None이면 행 설정을 따름
    border_fill: Optional[int] = None
    para_pr: Optional[int] = None
    char_pr: Optional[int] = None
    # 셀 내 여러 문단 (None이면 text 단일 문단)
    paragraphs: Optional[list[dict]] = None
    # 세로 정렬: "CENTER" | "TOP" | "BOTTOM"
    vert_align: str = "CENTER"

    def effective_border(self, row_default: int) -> int:
        return self.border_fill if self.border_fill is not None else row_default

    def effective_para(self, row_default: int) -> int:
        return self.para_pr if self.para_pr is not None else row_default

    def effective_char(self, row_default: int) -> int:
        return self.char_pr if self.char_pr is not None else row_default


@dataclass
class Row:
    """표의 한 행."""
    cells: list[Cell]
    is_header: bool = False
    height: int = DEFAULT_ROW_HEIGHT
    border_fill: int = BORDER_DATA  # 기본 데이터 테두리
    para_pr: int = PARA_CENTER
    char_pr: int = CHAR_NORMAL

    @classmethod
    def header(cls, cells: list[Cell | str], height: int = DEFAULT_ROW_HEIGHT) -> "Row":
        """헤더 행 생성 (배경색 + 볼드)."""
        cell_objs = [c if isinstance(c, Cell) else Cell(c) for c in cells]
        return cls(
            cells=cell_objs,
            is_header=True,
            height=height,
            border_fill=BORDER_HEADER,
            para_pr=PARA_CENTER,
            char_pr=CHAR_HEADER,
        )

    @classmethod
    def data(cls, cells: list[Cell | str], height: int = DEFAULT_ROW_HEIGHT,
             para_pr: int = PARA_CENTER) -> "Row":
        """데이터 행 생성."""
        cell_objs = [c if isinstance(c, Cell) else Cell(c) for c in cells]
        return cls(
            cells=cell_objs,
            is_header=False,
            height=height,
            border_fill=BORDER_DATA,
            para_pr=para_pr,
            char_pr=CHAR_NORMAL,
        )


# ──────────────────────────────────────────────────────────────────────────────
# ID 생성기
# ──────────────────────────────────────────────────────────────────────────────

class _IdGen:
    """문단 ID 순차 생성기."""
    def __init__(self, start: int = 1000000200):
        self._next = start

    def next(self) -> int:
        v = self._next
        self._next += 1
        return v


# ──────────────────────────────────────────────────────────────────────────────
# 셀 XML 생성
# ──────────────────────────────────────────────────────────────────────────────

def _build_cell_xml(
    cell: Cell,
    col_addr: int,
    row_addr: int,
    width: int,
    height: int,
    row: Row,
    id_gen: _IdGen,
    cell_margin_left: int = 284,
    cell_margin_right: int = 284,
    cell_margin_top: int = 141,
    cell_margin_bottom: int = 141,
) -> str:
    border = cell.effective_border(row.border_fill)
    para_pr = cell.effective_para(row.para_pr)
    char_pr = cell.effective_char(row.char_pr)
    vert = cell.vert_align

    # 내부 문단 목록 결정
    if cell.paragraphs:
        paras = cell.paragraphs
    else:
        paras = [{"text": cell.text, "para_pr": para_pr, "char_pr": char_pr}]

    para_xmls = []
    for p in paras:
        pid = id_gen.next()
        pp = p.get("para_pr", para_pr)
        cp = p.get("char_pr", char_pr)
        txt = p.get("text", "")
        runs = p.get("runs", None)

        if runs:
            # 복수 run (서식 혼합)
            run_xml = ""
            for r in runs:
                rcp = r.get("char_pr", cp)
                rtxt = r.get("text", "")
                run_xml += f'<hp:run charPrIDRef="{rcp}"><hp:t>{_esc(rtxt)}</hp:t></hp:run>\n              '
            para_xmls.append(
                f'<hp:p paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" '
                f'columnBreak="0" merged="0" id="{pid}">\n              '
                f'{run_xml.strip()}\n            </hp:p>'
            )
        else:
            para_xmls.append(
                f'<hp:p paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" '
                f'columnBreak="0" merged="0" id="{pid}">'
                f'<hp:run charPrIDRef="{cp}"><hp:t>{_esc(txt)}</hp:t></hp:run>'
                f'</hp:p>'
            )

    paras_xml = "\n            ".join(para_xmls)

    col_span = cell.col_span
    row_span = cell.row_span

    return f"""        <hp:tc name="" header="{'1' if row.is_header else '0'}" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{border}">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{vert}"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            {paras_xml}
          </hp:subList>
          <hp:cellAddr colAddr="{col_addr}" rowAddr="{row_addr}"/>
          <hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/>
          <hp:cellSz width="{width}" height="{height}"/>
          <hp:cellMargin left="{cell_margin_left}" right="{cell_margin_right}" top="{cell_margin_top}" bottom="{cell_margin_bottom}"/>
        </hp:tc>"""


def _esc(text: str) -> str:
    """XML 특수문자 이스케이프."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ──────────────────────────────────────────────────────────────────────────────
# TableBuilder 메인 클래스
# ──────────────────────────────────────────────────────────────────────────────

class TableBuilder:
    """
    HWPX 표 XML 빌더.

    Parameters
    ----------
    col_widths : list[int]
        열 너비 목록 (HWPUNIT). 합계가 A4 본문폭(42520)과 일치해야 함.
    border_fill_table : int
        표 외곽 테두리 borderFillIDRef (기본 3)
    id_start : int
        내부 문단 ID 시작값 (다른 문단과 겹치지 않게 설정)
    validate_width : bool
        열 너비 합계 = A4 본문폭 검증 여부 (기본 True)
    """

    def __init__(
        self,
        col_widths: list[int],
        border_fill_table: int = BORDER_TABLE,
        id_start: int = 1000000200,
        validate_width: bool = True,
    ):
        if validate_width:
            total = sum(col_widths)
            if total != A4_CONTENT_WIDTH:
                raise ValueError(
                    f"열 너비 합계({total})가 A4 본문폭({A4_CONTENT_WIDTH})과 다릅니다. "
                    f"차이: {total - A4_CONTENT_WIDTH}. validate_width=False로 비활성화 가능."
                )
        self.col_widths = col_widths
        self.border_fill_table = border_fill_table
        self._rows: list[Row] = []
        self._id_gen = _IdGen(id_start)

    # ── 행 추가 convenience 메서드 ────────────────────────────────────────────

    def header_row(
        self,
        cells: list[str | Cell],
        height: int = DEFAULT_ROW_HEIGHT,
    ) -> "TableBuilder":
        """헤더 행 추가 (배경색 + 볼드)."""
        self._rows.append(Row.header(cells, height=height))
        return self

    def data_row(
        self,
        cells: list[str | Cell],
        height: int = DEFAULT_ROW_HEIGHT,
        para_pr: int = PARA_CENTER,
    ) -> "TableBuilder":
        """데이터 행 추가."""
        self._rows.append(Row.data(cells, height=height, para_pr=para_pr))
        return self

    def add_row(self, row: Row) -> "TableBuilder":
        """Row 객체 직접 추가 (세밀한 제어가 필요할 때)."""
        self._rows.append(row)
        return self

    # ── XML 빌드 ─────────────────────────────────────────────────────────────

    def build(
        self,
        table_id: int = 1000000099,
        para_id_before: Optional[int] = None,
        para_id_after: Optional[int] = None,
    ) -> str:
        """
        표를 감싸는 <hp:p> 태그 포함 전체 XML 반환.

        Parameters
        ----------
        table_id : int
            표 요소의 id 속성값
        para_id_before : int | None
            표 앞 빈 문단 id (None이면 생략)
        para_id_after : int | None
            표 뒤 빈 문단 id (None이면 생략)
        """
        if not self._rows:
            raise ValueError("행이 없습니다. header_row() 또는 data_row()를 먼저 호출하세요.")

        col_count = len(self.col_widths)
        row_count = len(self._rows)

        # 전체 높이 계산
        total_height = sum(r.height for r in self._rows)
        total_width = sum(self.col_widths)

        # 행 XML 조립
        rows_xml = self._build_rows_xml()

        # 표 XML
        tbl_xml = f"""    <hp:tbl id="{table_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM"
            textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL"
            repeatHeader="1" rowCnt="{row_count}" colCnt="{col_count}" cellSpacing="0"
            borderFillIDRef="{self.border_fill_table}" noAdjust="0">
      <hp:sz width="{total_width}" widthRelTo="ABSOLUTE" height="{total_height}" heightRelTo="ABSOLUTE" protect="0"/>
      <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"
              holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP"
              horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
      <hp:outMargin left="0" right="0" top="0" bottom="0"/>
      <hp:inMargin left="0" right="0" top="0" bottom="0"/>
{rows_xml}
    </hp:tbl>"""

        # 표를 감싸는 문단
        wrap_p_id = self._id_gen.next()
        result_parts = []

        if para_id_before is not None:
            result_parts.append(
                f'  <hp:p id="{para_id_before}" paraPrIDRef="0" styleIDRef="0" '
                f'pageBreak="0" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>'
            )

        result_parts.append(
            f'  <hp:p id="{wrap_p_id}" paraPrIDRef="0" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0">\n'
            f'    <hp:run charPrIDRef="0">\n'
            f'{tbl_xml}\n'
            f'    </hp:run>\n'
            f'  </hp:p>'
        )

        if para_id_after is not None:
            result_parts.append(
                f'  <hp:p id="{para_id_after}" paraPrIDRef="0" styleIDRef="0" '
                f'pageBreak="0" columnBreak="0" merged="0">'
                f'<hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>'
            )

        return "\n".join(result_parts)

    def _build_rows_xml(self) -> str:
        row_xmls = []
        for row_addr, row in enumerate(self._rows):
            cell_xmls = []
            col_addr = 0
            for cell in row.cells:
                width = self._calc_cell_width(col_addr, cell.col_span)
                cell_xml = _build_cell_xml(
                    cell=cell,
                    col_addr=col_addr,
                    row_addr=row_addr,
                    width=width,
                    height=row.height,
                    row=row,
                    id_gen=self._id_gen,
                )
                cell_xmls.append(cell_xml)
                col_addr += cell.col_span

            row_xmls.append("      <hp:tr>\n" + "\n".join(cell_xmls) + "\n      </hp:tr>")

        return "\n".join(row_xmls)

    def _calc_cell_width(self, col_start: int, col_span: int) -> int:
        """병합을 고려한 셀 너비 계산."""
        return sum(self.col_widths[col_start:col_start + col_span])

    # ── 진단 ─────────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """표 구조 요약 (디버깅용)."""
        lines = [
            f"TableBuilder 요약",
            f"  열 수: {len(self.col_widths)}",
            f"  열 너비: {self.col_widths}",
            f"  합계: {sum(self.col_widths)} (A4={A4_CONTENT_WIDTH})",
            f"  행 수: {len(self._rows)}",
        ]
        for i, row in enumerate(self._rows):
            tag = "[H]" if row.is_header else "[D]"
            texts = [c.text[:15] for c in row.cells]
            lines.append(f"  Row {i} {tag}: {texts}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────────────────────────────────────

def even_col_widths(n_cols: int, total: int = A4_CONTENT_WIDTH) -> list[int]:
    """
    균등 열 너비 계산 (합계 보정 포함).

    예: even_col_widths(3) → [14173, 14173, 14174]
    """
    base = total // n_cols
    remainder = total - base * n_cols
    widths = [base] * n_cols
    widths[-1] += remainder
    return widths


def ratio_col_widths(ratios: list[int], total: int = A4_CONTENT_WIDTH) -> list[int]:
    """
    비율 기반 열 너비 계산.

    예: ratio_col_widths([1, 4]) → [8504, 34016]
    예: ratio_col_widths([1, 2, 2]) → [8504, 17008, 17008]
    """
    total_ratio = sum(ratios)
    widths = []
    accumulated = 0
    for i, r in enumerate(ratios):
        if i == len(ratios) - 1:
            widths.append(total - accumulated)
        else:
            w = round(total * r / total_ratio)
            widths.append(w)
            accumulated += w
    return widths


# ──────────────────────────────────────────────────────────────────────────────
# CLI 데모
# ──────────────────────────────────────────────────────────────────────────────

def _demo_basic():
    """기본 표 생성 데모."""
    print("=== 기본 표 (3열 균등) ===\n")
    widths = even_col_widths(3)
    print(f"열 너비: {widths}, 합계={sum(widths)}\n")

    tb = TableBuilder(col_widths=widths)
    tb.header_row(["부서", "매출(억원)", "전년대비"])
    tb.data_row(["영업부", "125", "+12%"])
    tb.data_row(["마케팅부", "89", "+5%"])
    tb.data_row(["개발부", "42", "+18%"])

    print(tb.summary())
    print("\n--- 생성된 XML (일부) ---")
    xml = tb.build(table_id=1000000099)
    # 처음 20줄만 출력
    lines = xml.split("\n")
    print("\n".join(lines[:20]))
    print(f"... (총 {len(lines)}줄)")


def _demo_ratio():
    """비율 열 너비 데모."""
    print("=== 비율 열 너비 (1:4) ===\n")
    widths = ratio_col_widths([1, 4])
    print(f"열 너비: {widths}, 합계={sum(widths)}\n")

    tb = TableBuilder(col_widths=widths)
    tb.header_row(["항목", "내용"])
    tb.data_row(["회사명", "클리어테크(ClearTech)"])
    tb.data_row(["업종", "B2B SaaS — AI 기반 회계·세무 자동화"])
    tb.data_row(["매출", "연 42억원 (전년 대비 +31% 성장)"])

    print(tb.summary())


def _demo_merge():
    """셀 병합 데모."""
    print("=== 셀 병합 (colSpan) ===\n")
    widths = ratio_col_widths([1, 1, 2])
    print(f"열 너비: {widths}, 합계={sum(widths)}\n")

    tb = TableBuilder(col_widths=widths, validate_width=False)
    # 실제 validate_width=False는 합계가 다를 때만 필요
    tb = TableBuilder(col_widths=widths)

    # 헤더: 첫 셀이 2열 병합
    tb.add_row(Row.header([
        Cell("구분", col_span=2),
        Cell("성과"),
    ]))
    tb.data_row(["Q1", "1월", "달성"])
    tb.data_row(["", "2월", "미달성"])

    print(tb.summary())


def main():
    parser = argparse.ArgumentParser(description="HWPX 표 XML 빌더 데모")
    parser.add_argument("--demo", action="store_true", help="기본 사용 예시")
    parser.add_argument("--demo-ratio", action="store_true", help="비율 열 너비 예시")
    parser.add_argument("--demo-merge", action="store_true", help="셀 병합 예시")
    parser.add_argument("--widths", nargs="+", type=int, help="열 너비 목록 (합계=42520)")
    args = parser.parse_args()

    if args.demo:
        _demo_basic()
    elif args.demo_ratio:
        _demo_ratio()
    elif args.demo_merge:
        _demo_merge()
    elif args.widths:
        print(f"열 너비: {args.widths}")
        print(f"합계: {sum(args.widths)} (A4={A4_CONTENT_WIDTH})")
        print(f"차이: {sum(args.widths) - A4_CONTENT_WIDTH}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
