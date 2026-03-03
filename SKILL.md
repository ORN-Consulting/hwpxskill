---
name: hwpx
description: "한글(HWPX) 문서 생성/읽기/편집 스킬. .hwpx 파일, 한글 문서, Hancom, OWPML 관련 요청 시 사용."
---

# HWPX 문서 스킬 — 레퍼런스 복원 우선(XML-first) 워크플로우

한글(Hancom Office)의 HWPX 파일을 **XML 직접 작성** 중심으로 생성, 편집, 읽기할 수 있는 스킬.  
HWPX는 ZIP 기반 XML 컨테이너(OWPML 표준)이다. python-hwpx API의 서식 버그를 완전히 우회하며, 세밀한 서식 제어가 가능하다.

---

## 기본 동작 모드 (필수): 첨부 HWPX 분석 → 고유 XML 복원(99% 근접) → 요청 반영 재작성

사용자가 `.hwpx`를 첨부한 경우, 이 스킬은 아래 순서를 **기본값**으로 따른다.

1. **레퍼런스 확보**: 첨부된 HWPX를 기준 문서로 사용
2. **심층 분석/추출**: `analyze_template.py`로 `header.xml`, `section0.xml` 추출
3. **구조 복원**: header 스타일 ID/표 구조/셀 병합/여백/문단 흐름을 최대한 동일하게 유지
4. **요청 반영 재작성**: 사용자가 요구한 텍스트/데이터만 교체하고 구조는 보존
5. **빌드/검증**: `build_hwpx.py` + `validate.py`(구조+시맨틱)로 결과 산출 및 무결성 확인
6. **쪽수 가드(필수)**: `page_guard.py`로 레퍼런스 대비 페이지 드리프트 위험 검사

### 99% 근접 복원 기준 (실무 체크리스트)

- `charPrIDRef`, `paraPrIDRef`, `borderFillIDRef` 참조 체계 동일
- 표의 `rowCnt`, `colCnt`, `colSpan`, `rowSpan`, `cellSz`, `cellMargin` 동일
- 문단 순서, 문단 수, 주요 빈 줄/구획 위치 동일
- 페이지/여백/섹션(secPr) 동일
- 변경은 사용자 요청 범위(본문 텍스트, 값, 항목명 등)로 제한

### 쪽수 동일(100%) 필수 기준

- 사용자가 레퍼런스를 제공한 경우 **결과 문서의 최종 쪽수는 레퍼런스와 동일해야 한다**
- 쪽수가 늘어날 가능성이 보이면 먼저 텍스트를 압축/요약해서 기존 레이아웃에 맞춘다
- 사용자 명시 요청 없이 `hp:p`, `hp:tbl`, `rowCnt`, `colCnt`, `pageBreak`, `secPr`를 변경하지 않는다
- `validate.py` 통과만으로 완료 처리하지 않는다. 반드시 `page_guard.py`도 통과해야 한다
- `page_guard.py` 실패 시 결과를 완료로 제출하지 않고, 원인(길이 과다/구조 변경)을 수정 후 재빌드한다

### 기본 실행 명령 (첨부 레퍼런스가 있을 때)

```bash
SKILL_DIR="/mnt/skills/user/hwpx"

# 1) 레퍼런스 분석 + XML 추출
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx \
  --extract-header /tmp/ref_header.xml \
  --extract-section /tmp/ref_section.xml

# 2) /tmp/ref_section.xml을 복제해 /tmp/new_section0.xml 작성
#    (구조 유지, 텍스트/데이터만 요청에 맞게 수정)

# 3) 복원 빌드
python3 "$SKILL_DIR/scripts/build_hwpx.py" \
  --header /tmp/ref_header.xml \
  --section /tmp/new_section0.xml \
  --output result.hwpx

# 4) 구조 + 시맨틱 검증
python3 "$SKILL_DIR/scripts/validate.py" result.hwpx

# 5) 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/page_guard.py" \
  --reference reference.hwpx \
  --output result.hwpx
```

---

## 환경

### Claude.ai 채팅 환경 (기본)

`lxml`이 이미 설치되어 있으므로 **venv 없이 직접 실행**한다.

```bash
SKILL_DIR="/mnt/skills/user/hwpx"

python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section my.xml --output result.hwpx
```

### Claude Code / 로컬 프로젝트 환경

```bash
SKILL_DIR="<프로젝트 경로>/skills/hwpx"
VENV="<프로젝트>/.venv/bin/activate"
source "$VENV"   # lxml 설치된 venv 필요

python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section my.xml --output result.hwpx
```

---

## 디렉토리 구조

```
hwpx/
├── SKILL.md
├── scripts/
│   ├── office/
│   │   ├── unpack.py          # HWPX → 디렉토리 (XML pretty-print)
│   │   └── pack.py            # 디렉토리 → HWPX
│   ├── build_hwpx.py          # 핵심: 템플릿 + XML → HWPX 조립 (다중 섹션, proposal 포함)
│   ├── table_builder.py       # 표 XML 생성 헬퍼 (반복 XML 자동화)
│   ├── analyze_template.py    # HWPX 심층 분석 (레퍼런스 기반 생성용)
│   ├── validate.py            # HWPX 구조 + 시맨틱 검증 (강화됨)
│   ├── page_guard.py          # 레퍼런스 대비 페이지 드리프트 위험 검사 (필수 게이트)
│   └── text_extract.py        # 텍스트 추출
├── templates/
│   ├── base/                  # ZIP 컨테이너 + 공통 설정
│   ├── gonmun/                # 공문 오버레이
│   ├── report/                # 보고서 오버레이
│   ├── minutes/               # 회의록 오버레이
│   └── proposal/              # 제안서 오버레이 (색상 헤더바, 번호 배지)
├── examples/
└── references/
    └── hwpx-format.md
```

---

## 워크플로우 1: XML-first 문서 생성 (보조 워크플로우 — 레퍼런스 파일이 없을 때만)

### 흐름

1. **템플릿 선택** (base / gonmun / report / minutes / proposal)
2. **section0.xml 작성** (본문 내용) — 표는 `table_builder.py` 활용
3. **(선택) 추가 섹션** — `--extra-section sec1.xml`으로 다중 섹션
4. **build_hwpx.py로 빌드**
5. **validate.py로 검증** (구조 + 시맨틱 자동 수행)

> 원칙: 사용자가 레퍼런스 HWPX를 제공한 경우에는 이 워크플로우 대신 상단의 **"기본 동작 모드(레퍼런스 복원 우선)"**를 사용한다.

### 기본 사용법

```bash
# 빈 문서
python3 "$SKILL_DIR/scripts/build_hwpx.py" --output result.hwpx

# 템플릿 사용
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --output result.hwpx

# 커스텀 section0.xml
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section my.xml --output result.hwpx

# 다중 섹션 (가로/세로 혼용 등)
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section sec0.xml \
  --extra-section sec1.xml --extra-section sec2.xml --output result.hwpx

# 메타데이터
python3 "$SKILL_DIR/scripts/build_hwpx.py" --template report --section my.xml \
  --title "제목" --creator "작성자" --output result.hwpx
```

---

## section0.xml 작성 가이드

### 필수 구조

section0.xml의 **첫 문단 첫 런**에 반드시 `<hp:secPr>` + `<hp:colPr>` 포함:

```xml
<?xml version='1.0' encoding='UTF-8'?>
<hs:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"
        xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"
        xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head">

  <!-- 첫 문단: secPr + colPr 필수 -->
  <hp:p id="1000000001" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
    <hp:run charPrIDRef="0">
      <hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000"
                tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1"
                memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">
        <hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>
        <hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>
        <hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0"
                       border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0"
                       hideFirstEmptyLine="0" showLineNumber="0"/>
        <hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>
        <hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">
          <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504"
                     top="5668" bottom="4252"/>
        </hp:pagePr>
      </hp:secPr>
      <hp:ctrl>
        <hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>
      </hp:ctrl>
    </hp:run>
    <hp:run charPrIDRef="0"><hp:t/></hp:run>
  </hp:p>

  <!-- 이하 본문 -->
</hs:sec>
```

**Tip**: `templates/base/Contents/section0.xml` 의 첫 문단을 그대로 복사하면 된다.

### 다중 섹션의 secPr

추가 섹션(section1.xml~)도 동일한 구조를 따르되, **ID는 다른 섹션과 겹치지 않게** 큰 수로 시작:

```xml
<!-- section1.xml: ID를 2000000001부터 시작 -->
<hp:p id="2000000001" ...>

<!-- section2.xml: ID를 3000000001부터 시작 -->
<hp:p id="3000000001" ...>
```

가로 방향 페이지는 secPr의 pagePr에서 landscape와 width/height를 변경:

```xml
<!-- 가로 방향 A4 -->
<hp:pagePr landscape="LANDSCAPE" width="84186" height="59528" gutterType="LEFT_ONLY">
  <hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504"
             top="5668" bottom="4252"/>
</hp:pagePr>
```

### 문단 기본 패턴

```xml
<!-- 일반 문단 -->
<hp:p id="1000000002" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t>본문 텍스트</hp:t></hp:run>
</hp:p>

<!-- 빈 줄 -->
<hp:p id="1000000003" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t/></hp:run>
</hp:p>

<!-- 서식 혼합 (한 문단에 여러 스타일) -->
<hp:p id="1000000004" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0"><hp:t>일반 텍스트 </hp:t></hp:run>
  <hp:run charPrIDRef="9"><hp:t>볼드 텍스트</hp:t></hp:run>
  <hp:run charPrIDRef="0"><hp:t> 다시 일반</hp:t></hp:run>
</hp:p>
```

---

## 표 작성 — table_builder.py 사용 (권장)

표 XML은 셀 수에 비례해 장황해지므로 **반드시 table_builder.py를 사용**한다.  
직접 XML 작성은 ID 충돌, 열 너비 오류, 태그 누락의 원인이 된다.

### Python 코드에서 사용

```python
import sys
sys.path.insert(0, f"{SKILL_DIR}/scripts")
from table_builder import TableBuilder, even_col_widths, ratio_col_widths, Cell, Row

# ① 균등 3열 표
widths = even_col_widths(3)        # [14173, 14173, 14174], 합계=42520
tb = TableBuilder(col_widths=widths, id_start=1000000100)
tb.header_row(["항목", "값", "비고"])
tb.data_row(["매출", "42억원", "+31%"])
tb.data_row(["직원", "68명", "-"])
xml = tb.build(table_id=1000000099)
# → section0.xml 내 <hp:p>...</hp:p> 블록 반환

# ② 비율 2열 표 (라벨:내용 = 1:4)
widths = ratio_col_widths([1, 4])  # [8504, 34016]
tb = TableBuilder(col_widths=widths, id_start=1000000200)
tb.header_row(["항목", "내용"])
tb.data_row(["회사명", "클리어테크"])

# ③ 셀 병합 (colSpan)
widths = ratio_col_widths([1, 1, 2])
tb = TableBuilder(col_widths=widths, id_start=1000000300)
tb.add_row(Row.header([
    Cell("구분", col_span=2),   # 2열 병합
    Cell("성과"),
]))
tb.data_row(["Q1", "1월", "달성"])

# ④ 세밀한 제어 (vert_align, para_pr, char_pr 개별 지정)
tb.add_row(Row.data([
    Cell("합계", vert_align="CENTER", char_pr=9),  # 볼드 셀
    Cell("total"),
]))
```

### table_builder.py 주요 API

| 함수/메서드 | 설명 |
|---|---|
| `even_col_widths(n)` | 균등 열 너비 (합계 자동 보정) |
| `ratio_col_widths([1,2,3])` | 비율 기반 열 너비 |
| `TableBuilder(col_widths, id_start)` | 빌더 생성 |
| `.header_row(cells, height)` | 헤더 행 추가 (배경색+볼드 자동) |
| `.data_row(cells, height, para_pr)` | 데이터 행 추가 |
| `.add_row(Row)` | Row 객체 직접 추가 (세밀한 제어) |
| `.build(table_id)` | 표 XML 문자열 반환 |
| `.summary()` | 표 구조 요약 출력 (디버깅) |
| `Cell(text, col_span, row_span, vert_align)` | 셀 데이터 객체 |

### 열 너비 규칙

- **A4 본문폭**: 42520 HWPUNIT = 59528(용지) - 8504×2(좌우여백)
- **열 너비 합 = 42520** (TableBuilder가 자동 검증)
- validate_width=False로 비표준 너비 허용 가능 (비권장)

---

## 직접 표 XML 작성 (table_builder 불가 시 참조용)

```xml
<hp:p id="고유ID" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">
  <hp:run charPrIDRef="0">
    <hp:tbl id="고유ID" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM"
            textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL"
            repeatHeader="1" rowCnt="행수" colCnt="열수" cellSpacing="0"
            borderFillIDRef="3" noAdjust="0">
      <hp:sz width="42520" widthRelTo="ABSOLUTE" height="전체높이" heightRelTo="ABSOLUTE" protect="0"/>
      <hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0"
              holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP"
              horzAlign="LEFT" vertOffset="0" horzOffset="0"/>
      <hp:outMargin left="0" right="0" top="0" bottom="0"/>
      <hp:inMargin left="0" right="0" top="0" bottom="0"/>
      <hp:tr>
        <hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="4">
          <hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER"
                     linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0"
                     hasTextRef="0" hasNumRef="0">
            <hp:p paraPrIDRef="21" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="고유ID">
              <hp:run charPrIDRef="9"><hp:t>헤더 셀</hp:t></hp:run>
            </hp:p>
          </hp:subList>
          <hp:cellAddr colAddr="0" rowAddr="0"/>
          <hp:cellSpan colSpan="1" rowSpan="1"/>
          <hp:cellSz width="열너비" height="행높이"/>
          <hp:cellMargin left="284" right="284" top="141" bottom="141"/>
        </hp:tc>
      </hp:tr>
    </hp:tbl>
  </hp:run>
</hp:p>
```

---

## 워크플로우 2: 기존 문서 편집 (unpack → Edit → pack)

```bash
# 1. HWPX → 디렉토리
python3 "$SKILL_DIR/scripts/office/unpack.py" document.hwpx ./unpacked/

# 2. XML 직접 편집
#    본문: ./unpacked/Contents/section0.xml
#    스타일: ./unpacked/Contents/header.xml

# 3. 다시 HWPX로 패키징
python3 "$SKILL_DIR/scripts/office/pack.py" ./unpacked/ edited.hwpx

# 4. 구조 + 시맨틱 검증
python3 "$SKILL_DIR/scripts/validate.py" edited.hwpx
```

---

## 워크플로우 3: 읽기/텍스트 추출

```bash
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx --include-tables
python3 "$SKILL_DIR/scripts/text_extract.py" document.hwpx --format markdown
```

---

## 워크플로우 4: 검증 (구조 + 시맨틱 강화)

```bash
# 구조 + 시맨틱 검증 (기본)
python3 "$SKILL_DIR/scripts/validate.py" document.hwpx

# 구조 검증만 (빠른 확인)
python3 "$SKILL_DIR/scripts/validate.py" document.hwpx --no-semantic
```

**검증 항목:**

| 범주 | 항목 |
|---|---|
| 구조 | ZIP 유효성, 필수 파일 존재, mimetype 내용/위치/압축방식, XML well-formedness |
| 시맨틱 | charPrIDRef / paraPrIDRef 참조 정합성 (section→header) |
| 시맨틱 | itemCnt 와 실제 자식 수 일치 |
| 시맨틱 | 표 열 너비 합계 = 표 선언 너비 |
| 시맨틱 | 문단 ID 유일성 (다중 섹션 포함) |

---

## 워크플로우 5: 레퍼런스 기반 문서 생성 (첨부 HWPX가 있을 때 기본 적용)

```bash
# 1. 심층 분석
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx

# 2. header.xml과 section0.xml을 추출
python3 "$SKILL_DIR/scripts/analyze_template.py" reference.hwpx \
  --extract-header /tmp/ref_header.xml \
  --extract-section /tmp/ref_section.xml

# 3. 추출한 header.xml + 새 section0.xml로 빌드
python3 "$SKILL_DIR/scripts/build_hwpx.py" \
  --header /tmp/ref_header.xml \
  --section /tmp/new_section0.xml \
  --output result.hwpx

# 4. 구조 + 시맨틱 검증
python3 "$SKILL_DIR/scripts/validate.py" result.hwpx

# 5. 쪽수 드리프트 가드 (필수)
python3 "$SKILL_DIR/scripts/page_guard.py" \
  --reference reference.hwpx \
  --output result.hwpx
```

---

## 워크플로우 6: 쪽수 가드 단독 실행

```bash
# 기본 (텍스트 15%, 문단별 25% 편차 허용)
python3 "$SKILL_DIR/scripts/page_guard.py" \
  --reference reference.hwpx \
  --output result.hwpx

# 허용 편차 조정 (더 엄격하게)
python3 "$SKILL_DIR/scripts/page_guard.py" \
  --reference reference.hwpx \
  --output result.hwpx \
  --max-text-delta-ratio 0.10 \
  --max-paragraph-delta-ratio 0.15

# 메트릭 JSON 출력 (디버깅)
python3 "$SKILL_DIR/scripts/page_guard.py" \
  --reference reference.hwpx \
  --output result.hwpx \
  --json
```

**page_guard 검사 항목:**

| 항목 | 설명 |
|---|---|
| 문단 수 | 레퍼런스와 동일해야 함 |
| 표 수 / 표 구조 | rowCnt, colCnt, width, height, pageBreak 동일 |
| 명시적 pageBreak / columnBreak 수 | 동일해야 함 |
| 전체 텍스트 길이 편차 | 기본 15% 이내 |
| 문단별 텍스트 길이 편차 | 기본 25% 이내 |

---

## 템플릿별 스타일 ID 맵

### report (보고서) — 가장 범용

| ID | 유형 | 설명 |
|----|------|------|
| charPr 0 | 글자 | 10pt 기본 |
| charPr 7 | 글자 | 20pt 볼드 (문서 제목) |
| charPr 8 | 글자 | 14pt 볼드 (소제목) |
| charPr 9 | 글자 | 10pt 볼드 (표 헤더) |
| charPr 10 | 글자 | 10pt 볼드+밑줄 (강조) |
| charPr 11 | 글자 | 9pt (소형/각주) |
| charPr 12 | 글자 | 16pt 볼드 (1줄 제목) |
| charPr 13 | 글자 | 12pt 볼드 함초롬돋움 (섹션 헤더) |
| paraPr 0 | 문단 | JUSTIFY, 160% |
| paraPr 20 | 문단 | CENTER, 160% |
| paraPr 21 | 문단 | CENTER, 130% (표 셀) |
| paraPr 22 | 문단 | JUSTIFY, 130% (표 셀) |
| paraPr 23 | 문단 | RIGHT, 160% |
| paraPr 24 | 문단 | JUSTIFY, left 600 (□ 들여쓰기) |
| paraPr 25 | 문단 | JUSTIFY, left 1200 (①②③ 들여쓰기) |
| paraPr 26 | 문단 | JUSTIFY, left 1800 (깊은 들여쓰기) |
| paraPr 27 | 문단 | LEFT, 상하단 테두리선 (섹션 헤더) |
| borderFill 3 | 테두리 | SOLID 0.12mm 4면 |
| borderFill 4 | 테두리 | SOLID 0.12mm + #DAEEF3 배경 |
| borderFill 5 | 테두리 | 상단 굵은선 + 하단 얇은선 (섹션 헤더) |

**섹션 헤더**: paraPr 27 + charPr 13 조합  
**들여쓰기**: 공백 문자 금지, 반드시 paraPr left margin 사용

### gonmun (공문)

| ID | 유형 | 설명 |
|----|------|------|
| charPr 7 | 글자 | 22pt 볼드 (기관명/제목) |
| charPr 8 | 글자 | 16pt 볼드 (서명자) |
| charPr 9 | 글자 | 8pt (하단 연락처) |
| charPr 10 | 글자 | 10pt 볼드 (표 헤더) |
| paraPr 20 | 문단 | CENTER, 160% |
| paraPr 21 | 문단 | CENTER, 130% (표 셀) |
| paraPr 22 | 문단 | JUSTIFY, 130% (표 셀) |
| borderFill 3 | 테두리 | SOLID 0.12mm 4면 |
| borderFill 4 | 테두리 | SOLID 0.12mm + #D6DCE4 배경 |

### minutes (회의록)

| ID | 유형 | 설명 |
|----|------|------|
| charPr 7 | 글자 | 18pt 볼드 (제목) |
| charPr 8 | 글자 | 12pt 볼드 (섹션 라벨) |
| charPr 9 | 글자 | 10pt 볼드 (표 헤더) |
| borderFill 4 | 테두리 | SOLID + #E2EFDA 배경 (녹색 계열) |

### proposal (제안서) — build_hwpx.py proposal 템플릿 지원

| ID | 유형 | 설명 |
|----|------|------|
| charPr 7 | 글자 | 20pt 볼드 (문서 제목) |
| charPr 8 | 글자 | 14pt 볼드 (소제목) |
| charPr 9 | 글자 | 10pt 볼드 (표 헤더) |
| charPr 10 | 글자 | 14pt 볼드 흰색 (대항목 번호, 녹색 배경) |
| charPr 11 | 글자 | 11pt 볼드 흰색 (소항목 번호, 파란 배경) |
| borderFill 5 | 테두리 | 올리브녹색 배경 #7B8B3D (대항목 번호 셀) |
| borderFill 6 | 테두리 | 연한 회색 배경 #F2F2F2 (대항목 제목 셀) |
| borderFill 7 | 테두리 | 파란색 배경 #4472C4 (소항목 번호 배지) |
| borderFill 8 | 테두리 | 하단 테두리만 #D0D0D0 (소항목 제목) |

---

## 스크립트 요약

| 스크립트 | 용도 |
|----------|------|
| `build_hwpx.py` | **핵심** — 템플릿 + XML → HWPX 조립. 다중 섹션(--extra-section), proposal 템플릿 지원 |
| `table_builder.py` | 표 XML 헬퍼. 반복 XML 자동 생성, 열 너비 자동 검증 |
| `validate.py` | **강화** — 구조 + 시맨틱 검증 (ID 참조, itemCnt, 표 너비, ID 유일성) |
| `page_guard.py` | **필수 게이트** — 레퍼런스 대비 페이지 드리프트 위험 검사 |
| `analyze_template.py` | HWPX 심층 분석 (레퍼런스 기반 생성의 청사진) |
| `office/unpack.py` | HWPX → 디렉토리 (XML pretty-print) |
| `office/pack.py` | 디렉토리 → HWPX (mimetype first) |
| `text_extract.py` | HWPX 텍스트 추출 |

---

## 단위 변환

| 값 | HWPUNIT | 의미 |
|----|---------|------|
| 1pt | 100 | 기본 단위 |
| 1mm | 283.5 | 밀리미터 |
| A4 폭 | 59528 | 210mm |
| A4 높이 | 84186 | 297mm |
| 좌우여백 | 8504 | 30mm |
| **본문폭** | **42520** | **150mm (A4-좌우여백×2)** |
| 행 높이 기본 | 2800 | 약 10mm |

---

## ID 규칙

- **문단 id**: `1000000001`부터 순차 증가
- **표 id**: `1000000099` 등 별도 범위 사용 권장
- **추가 섹션**: 섹션 번호 × 10억으로 시작 (section1→ 2000000001, section2→ 3000000001)
- **모든 id는 문서 전체에서 유일** (validate.py가 검증)

---

## Critical Rules

1. **HWPX만 지원**: `.hwp`(바이너리) 불가. 사용자가 `.hwp`를 제공하면 한글에서 다른 이름으로 저장 → HWPX로 재저장 안내
2. **secPr 필수**: section0.xml 첫 문단 첫 run에 secPr + colPr 포함
3. **mimetype 순서**: ZIP 첫 엔트리, ZIP_STORED
4. **네임스페이스 보존**: `hp:`, `hs:`, `hh:`, `hc:` 접두사 유지
5. **itemCnt 정합성**: header.xml의 charProperties/paraProperties/borderFills itemCnt = 실제 자식 수
6. **ID 참조 정합성**: section0의 charPrIDRef/paraPrIDRef가 header.xml 정의와 일치
7. **표 너비**: 열 너비 합 = 표 선언 너비 = 42520 (table_builder가 자동 검증)
8. **섹션 간 ID 유일성**: 다중 섹션 사용 시 섹션별로 ID 범위를 분리
9. **validate.py 필수**: 생성 후 반드시 구조+시맨틱 무결성 확인
10. **표는 table_builder 사용**: 직접 XML 작성 시 오류 빈발. table_builder.py 우선
11. **build_hwpx.py 우선**: 새 문서 생성은 build_hwpx.py 사용 (python-hwpx API 직접 호출 지양)
12. **빈 줄**: `<hp:t/>` 사용 (self-closing tag)
13. **레퍼런스 우선 강제**: 사용자가 HWPX를 첨부하면 반드시 `analyze_template.py` + 추출 XML 기반으로 복원/재작성할 것
14. **쪽수 동일 필수**: 레퍼런스 기반 작업에서는 최종 결과의 쪽수를 레퍼런스와 동일하게 유지할 것
15. **무단 페이지 증가 금지**: 사용자 명시 요청/승인 없이 쪽수 증가를 유발하는 구조 변경 금지
16. **구조 변경 제한**: 사용자 요청이 없는 한 문단/표의 추가·삭제·분할·병합 금지 (치환 중심 편집)
17. **page_guard 필수 통과**: `validate.py`와 별개로 `page_guard.py`를 반드시 통과해야 완료 처리 (레퍼런스 기반 작업 시)
