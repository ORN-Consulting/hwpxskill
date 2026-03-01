#!/usr/bin/env python3
"""Validate the structural integrity of an HWPX file.

구조 검증 (기존):
  - Valid ZIP archive
  - Required files present
  - mimetype content / position / compression
  - All XML well-formed

시맨틱 검증 (신규):
  - charPrIDRef / paraPrIDRef 참조 정합성 (section → header 정의 존재 여부)
  - itemCnt 와 실제 자식 수 일치
  - 표 열 너비 합계 = 표 선언 너비
  - 문단 ID 유일성

Usage:
    python validate.py document.hwpx
    python validate.py document.hwpx --strict   # 시맨틱 검증 포함 (기본)
    python validate.py document.hwpx --no-semantic  # 구조 검증만
"""

import argparse
import sys
from pathlib import Path
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from lxml import etree

REQUIRED_FILES = [
    "mimetype",
    "Contents/content.hpf",
    "Contents/header.xml",
    "Contents/section0.xml",
]
EXPECTED_MIMETYPE = "application/hwp+zip"

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
}


# ──────────────────────────────────────────────────────────────────────────────
# 기존 구조 검증
# ──────────────────────────────────────────────────────────────────────────────

def _structural_validate(hwpx_path: str, zf: ZipFile) -> list[str]:
    errors: list[str] = []
    names = zf.namelist()

    for required in REQUIRED_FILES:
        if required not in names:
            errors.append(f"[구조] 필수 파일 없음: {required}")

    if "mimetype" in names:
        mimetype_content = zf.read("mimetype").decode("utf-8").strip()
        if mimetype_content != EXPECTED_MIMETYPE:
            errors.append(f"[구조] mimetype 내용 오류: '{mimetype_content}'")
        if names[0] != "mimetype":
            errors.append(f"[구조] mimetype이 ZIP 첫 번째 엔트리 아님 (index={names.index('mimetype')})")
        info = zf.getinfo("mimetype")
        if info.compress_type != ZIP_STORED:
            errors.append(f"[구조] mimetype ZIP_STORED 아님 (compress_type={info.compress_type})")

    for name in names:
        if name.endswith(".xml") or name.endswith(".hpf"):
            try:
                etree.fromstring(zf.read(name))
            except etree.XMLSyntaxError as e:
                errors.append(f"[구조] XML 파싱 오류 {name}: {e}")

    return errors


# ──────────────────────────────────────────────────────────────────────────────
# 시맨틱 검증 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _collect_defined_ids(header_root) -> dict[str, set[int]]:
    """header.xml에서 정의된 ID 집합 수집."""
    defined: dict[str, set[int]] = {
        "charPr": set(),
        "paraPr": set(),
        "borderFill": set(),
    }
    for cp in header_root.findall(".//hh:charPr", NS):
        try:
            defined["charPr"].add(int(cp.get("id", -1)))
        except ValueError:
            pass
    for pp in header_root.findall(".//hh:paraPr", NS):
        try:
            defined["paraPr"].add(int(pp.get("id", -1)))
        except ValueError:
            pass
    for bf in header_root.findall(".//hh:borderFill", NS):
        try:
            defined["borderFill"].add(int(bf.get("id", -1)))
        except ValueError:
            pass
    return defined


def _check_itemcnt(header_root) -> list[str]:
    """itemCnt 속성과 실제 자식 수 일치 검증."""
    errors = []

    checks = [
        (".//hh:charProperties", "hh:charPr", "charProperties"),
        (".//hh:paraProperties", "hh:paraPr", "paraProperties"),
        (".//hh:borderFills",    "hh:borderFill", "borderFills"),
    ]
    for parent_xpath, child_tag, label in checks:
        parent_el = header_root.find(parent_xpath, NS)
        if parent_el is None:
            continue
        declared = parent_el.get("itemCnt")
        if declared is None:
            continue
        actual = len(parent_el.findall(child_tag, NS))
        try:
            if int(declared) != actual:
                errors.append(
                    f"[시맨틱] {label} itemCnt={declared} ≠ 실제 자식 수={actual}"
                )
        except ValueError:
            pass
    return errors


def _check_id_refs(section_root, defined: dict[str, set[int]]) -> list[str]:
    """section0.xml의 ID 참조가 header.xml 정의와 일치하는지 검증."""
    errors = []
    missing_char: set[int] = set()
    missing_para: set[int] = set()
    missing_border: set[int] = set()

    # 문단 paraPrIDRef
    for p in section_root.findall(".//hp:p", NS):
        ref = p.get("paraPrIDRef")
        if ref is not None:
            try:
                rid = int(ref)
                if rid not in defined["paraPr"]:
                    missing_para.add(rid)
            except ValueError:
                pass

    # 런 charPrIDRef
    for run in section_root.findall(".//hp:run", NS):
        ref = run.get("charPrIDRef")
        if ref is not None:
            try:
                rid = int(ref)
                if rid not in defined["charPr"]:
                    missing_char.add(rid)
            except ValueError:
                pass

    # 표/셀 borderFillIDRef
    for el in section_root.findall(".//hp:tbl", NS):
        ref = el.get("borderFillIDRef")
        if ref:
            try:
                rid = int(ref)
                if rid not in defined["borderFill"]:
                    missing_border.add(rid)
            except ValueError:
                pass
    for el in section_root.findall(".//hp:tc", NS):
        ref = el.get("borderFillIDRef")
        if ref:
            try:
                rid = int(ref)
                if rid not in defined["borderFill"]:
                    missing_border.add(rid)
            except ValueError:
                pass

    if missing_char:
        errors.append(f"[시맨틱] charPrIDRef 미정의 ID: {sorted(missing_char)}")
    if missing_para:
        errors.append(f"[시맨틱] paraPrIDRef 미정의 ID: {sorted(missing_para)}")
    if missing_border:
        errors.append(f"[시맨틱] borderFillIDRef 미정의 ID: {sorted(missing_border)}")

    return errors


def _check_table_widths(section_root) -> list[str]:
    """표 열 너비 합계 = 표 선언 너비 검증."""
    errors = []
    for tbl in section_root.findall(".//hp:tbl", NS):
        tbl_id = tbl.get("id", "?")
        sz = tbl.find("hp:sz", NS)
        if sz is None:
            continue
        declared_w = sz.get("width")
        if declared_w is None:
            continue
        declared_w = int(declared_w)

        # 첫 행에서 colSpan=1인 셀들의 너비 합산
        col_widths: dict[int, int] = {}
        for tr in tbl.findall("hp:tr", NS):
            for tc in tr.findall("hp:tc", NS):
                addr = tc.find("hp:cellAddr", NS)
                span = tc.find("hp:cellSpan", NS)
                csz = tc.find("hp:cellSz", NS)
                if addr is None or csz is None:
                    continue
                col_idx = int(addr.get("colAddr", -1))
                col_span = int(span.get("colSpan", 1)) if span is not None else 1
                if col_span == 1 and col_idx not in col_widths:
                    try:
                        col_widths[col_idx] = int(csz.get("width", 0))
                    except ValueError:
                        pass
            break  # 첫 행만 샘플링

        if col_widths:
            actual_w = sum(col_widths.values())
            if actual_w != declared_w:
                errors.append(
                    f"[시맨틱] 표 id={tbl_id}: 열너비 합계({actual_w}) ≠ 표 선언 너비({declared_w}), "
                    f"차이={actual_w - declared_w}"
                )

    return errors


def _check_para_id_uniqueness(section_roots: list) -> list[str]:
    """모든 섹션에 걸쳐 문단 ID 유일성 검증."""
    seen: dict[str, str] = {}  # id → 섹션명
    errors = []
    for section_name, root in section_roots:
        for p in root.findall(".//hp:p", NS):
            pid = p.get("id")
            if pid is None:
                continue
            if pid in seen:
                errors.append(
                    f"[시맨틱] 문단 id={pid} 중복 ({seen[pid]} 와 {section_name})"
                )
            else:
                seen[pid] = section_name
    return errors


# ──────────────────────────────────────────────────────────────────────────────
# 메인 검증 함수
# ──────────────────────────────────────────────────────────────────────────────

def validate(hwpx_path: str, semantic: bool = True) -> tuple[list[str], list[str]]:
    """
    HWPX 파일 검증.

    Returns
    -------
    (structural_errors, semantic_errors)
    """
    structural_errors: list[str] = []
    semantic_errors: list[str] = []
    path = Path(hwpx_path)

    if not path.is_file():
        return [f"파일 없음: {hwpx_path}"], []

    try:
        zf = ZipFile(hwpx_path, "r")
    except BadZipFile:
        return [f"유효하지 않은 ZIP: {hwpx_path}"], []

    with zf:
        # ── 구조 검증 ──
        structural_errors = _structural_validate(hwpx_path, zf)

        if not semantic:
            return structural_errors, []

        # ── 시맨틱 검증 ──
        names = zf.namelist()

        # header.xml 파싱
        if "Contents/header.xml" not in names:
            return structural_errors, ["[시맨틱] header.xml 없어서 시맨틱 검증 불가"]

        try:
            header_root = etree.fromstring(zf.read("Contents/header.xml"))
        except etree.XMLSyntaxError:
            return structural_errors, ["[시맨틱] header.xml 파싱 실패"]

        # 1. itemCnt 정합성
        semantic_errors.extend(_check_itemcnt(header_root))

        # 2. 정의된 ID 집합 수집
        defined = _collect_defined_ids(header_root)

        # 3. 섹션 파일들 파싱
        section_roots = []
        for name in sorted(names):
            if name.startswith("Contents/section") and name.endswith(".xml"):
                try:
                    root = etree.fromstring(zf.read(name))
                    section_roots.append((name, root))
                except etree.XMLSyntaxError:
                    pass  # 구조 검증에서 이미 잡힘

        # 4. ID 참조 정합성 (각 섹션)
        for section_name, section_root in section_roots:
            errs = _check_id_refs(section_root, defined)
            # 섹션 이름 prefix 추가
            for e in errs:
                semantic_errors.append(f"{e} ({section_name})")

        # 5. 표 열 너비 검증 (각 섹션)
        for section_name, section_root in section_roots:
            errs = _check_table_widths(section_root)
            for e in errs:
                semantic_errors.append(f"{e} ({section_name})")

        # 6. 문단 ID 유일성 (전체 섹션 통합)
        semantic_errors.extend(_check_para_id_uniqueness(section_roots))

    return structural_errors, semantic_errors


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the structural and semantic integrity of an HWPX file")
    parser.add_argument("input", help="Path to .hwpx file")
    parser.add_argument("--no-semantic", action="store_true", help="구조 검증만 수행 (시맨틱 검증 생략)")
    args = parser.parse_args()

    semantic = not args.no_semantic
    structural_errors, semantic_errors = validate(args.input, semantic=semantic)

    all_errors = structural_errors + semantic_errors
    if all_errors:
        print(f"INVALID: {args.input}", file=sys.stderr)
        if structural_errors:
            print("  [구조 오류]", file=sys.stderr)
            for err in structural_errors:
                print(f"    - {err}", file=sys.stderr)
        if semantic_errors:
            print("  [시맨틱 오류]", file=sys.stderr)
            for err in semantic_errors:
                print(f"    - {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"VALID: {args.input}")
        print(f"  All structural checks passed.")
        if semantic:
            print(f"  All semantic checks passed.")
            print(f"    (ID 참조 정합성, itemCnt, 표 너비, 문단 ID 유일성)")


if __name__ == "__main__":
    main()
