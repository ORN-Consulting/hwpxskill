#!/usr/bin/env python3
"""Build an HWPX document from templates and XML overrides.

Changes from original:
  - [FIX] proposal added to AVAILABLE_TEMPLATES
  - [NEW] --extra-section: multi-section support (section1.xml, section2.xml ...)
"""

import argparse
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
BASE_DIR = TEMPLATES_DIR / "base"

# [FIX] proposal 추가
AVAILABLE_TEMPLATES = ["gonmun", "report", "minutes", "proposal"]


def validate_xml(filepath: Path) -> None:
    try:
        etree.parse(str(filepath))
    except etree.XMLSyntaxError as e:
        raise SystemExit(f"Malformed XML in {filepath.name}: {e}")


def update_metadata(content_hpf: Path, title: str | None, creator: str | None) -> None:
    if not title and not creator:
        return
    tree = etree.parse(str(content_hpf))
    root = tree.getroot()
    ns = {"opf": "http://www.idpf.org/2007/opf/"}
    if title:
        title_el = root.find(".//opf:title", ns)
        if title_el is not None:
            title_el.text = title
    now = datetime.now(timezone.utc)
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    for meta in root.findall(".//opf:meta", ns):
        name = meta.get("name", "")
        if creator and name == "creator":
            meta.text = creator
        elif creator and name == "lastsaveby":
            meta.text = creator
        elif name == "CreatedDate":
            meta.text = iso_now
        elif name == "ModifiedDate":
            meta.text = iso_now
        elif name == "date":
            meta.text = now.strftime("%Y년 %m월 %d일")
    etree.indent(root, space="  ")
    tree.write(str(content_hpf), pretty_print=True, xml_declaration=True, encoding="UTF-8")


def register_extra_sections(content_hpf: Path, extra_sections: list[Path]) -> None:
    """[NEW] 추가 섹션을 content.hpf manifest/spine에 등록."""
    if not extra_sections:
        return
    tree = etree.parse(str(content_hpf))
    root = tree.getroot()
    ns_opf = "http://www.idpf.org/2007/opf/"
    ns = {"opf": ns_opf}
    manifest = root.find("opf:manifest", ns)
    spine = root.find("opf:spine", ns)
    for i, _ in enumerate(extra_sections, start=1):
        section_id = f"section{i}"
        href = f"Contents/section{i}.xml"
        if manifest.find(f"opf:item[@id='{section_id}']", ns) is None:
            item = etree.SubElement(manifest, f"{{{ns_opf}}}item")
            item.set("id", section_id)
            item.set("href", href)
            item.set("media-type", "application/xml")
        if spine.find(f"opf:itemref[@idref='{section_id}']", ns) is None:
            itemref = etree.SubElement(spine, f"{{{ns_opf}}}itemref")
            itemref.set("idref", section_id)
            itemref.set("linear", "yes")
    etree.indent(root, space="  ")
    tree.write(str(content_hpf), pretty_print=True, xml_declaration=True, encoding="UTF-8")


def pack_hwpx(input_dir: Path, output_path: Path) -> None:
    mimetype_file = input_dir / "mimetype"
    if not mimetype_file.is_file():
        raise SystemExit(f"Missing 'mimetype' in {input_dir}")
    all_files = sorted(
        p.relative_to(input_dir).as_posix()
        for p in input_dir.rglob("*")
        if p.is_file()
    )
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.write(mimetype_file, "mimetype", compress_type=ZIP_STORED)
        for rel_path in all_files:
            if rel_path == "mimetype":
                continue
            zf.write(input_dir / rel_path, rel_path, compress_type=ZIP_DEFLATED)


def validate_hwpx(hwpx_path: Path) -> list[str]:
    errors: list[str] = []
    required = ["mimetype", "Contents/content.hpf", "Contents/header.xml", "Contents/section0.xml"]
    try:
        from zipfile import BadZipFile
        zf = ZipFile(hwpx_path, "r")
    except BadZipFile:
        return [f"Not a valid ZIP: {hwpx_path}"]
    with zf:
        names = zf.namelist()
        for r in required:
            if r not in names:
                errors.append(f"Missing: {r}")
        if "mimetype" in names:
            content = zf.read("mimetype").decode("utf-8").strip()
            if content != "application/hwp+zip":
                errors.append(f"Bad mimetype content: {content}")
            if names[0] != "mimetype":
                errors.append("mimetype is not the first ZIP entry")
            info = zf.getinfo("mimetype")
            if info.compress_type != ZIP_STORED:
                errors.append("mimetype is not ZIP_STORED")
        for name in names:
            if name.endswith(".xml") or name.endswith(".hpf"):
                try:
                    etree.fromstring(zf.read(name))
                except etree.XMLSyntaxError as e:
                    errors.append(f"Malformed XML: {name}: {e}")
    return errors


def build(
    template: str | None,
    header_override: Path | None,
    section_override: Path | None,
    extra_sections: list[Path],
    title: str | None,
    creator: str | None,
    output: Path,
) -> None:
    if not BASE_DIR.is_dir():
        raise SystemExit(f"Base template not found: {BASE_DIR}")
    for es in extra_sections:
        if not es.is_file():
            raise SystemExit(f"Extra section file not found: {es}")

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir) / "build"
        shutil.copytree(BASE_DIR, work)

        if template:
            overlay_dir = TEMPLATES_DIR / template
            if not overlay_dir.is_dir():
                raise SystemExit(
                    f"Template '{template}' not found. Available: {', '.join(AVAILABLE_TEMPLATES)}"
                )
            for overlay_file in overlay_dir.iterdir():
                if overlay_file.is_file() and overlay_file.suffix == ".xml":
                    shutil.copy2(overlay_file, work / "Contents" / overlay_file.name)

        if header_override:
            if not header_override.is_file():
                raise SystemExit(f"Header file not found: {header_override}")
            shutil.copy2(header_override, work / "Contents" / "header.xml")

        if section_override:
            if not section_override.is_file():
                raise SystemExit(f"Section file not found: {section_override}")
            shutil.copy2(section_override, work / "Contents" / "section0.xml")

        # [NEW] 추가 섹션
        if extra_sections:
            for i, es_path in enumerate(extra_sections, start=1):
                shutil.copy2(es_path, work / "Contents" / f"section{i}.xml")
            register_extra_sections(work / "Contents" / "content.hpf", extra_sections)

        update_metadata(work / "Contents" / "content.hpf", title, creator)

        for xml_file in work.rglob("*.xml"):
            validate_xml(xml_file)
        for hpf_file in work.rglob("*.hpf"):
            validate_xml(hpf_file)

        pack_hwpx(work, output)

    errors = validate_hwpx(output)
    if errors:
        print(f"WARNING: {output} has issues:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"VALID: {output}")
        print(f"  Template: {template or 'base'}")
        if header_override:
            print(f"  Header: {header_override}")
        if section_override:
            print(f"  Section: {section_override}")
        if extra_sections:
            print(f"  Extra sections ({len(extra_sections)}): {[str(p) for p in extra_sections]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HWPX document from templates and XML overrides")
    parser.add_argument("--template", "-t", choices=AVAILABLE_TEMPLATES)
    parser.add_argument("--header", type=Path)
    parser.add_argument("--section", type=Path)
    # [NEW]
    parser.add_argument(
        "--extra-section", type=Path, action="append", dest="extra_sections", default=[],
        metavar="SECTION_XML",
        help="추가 섹션 XML (section1.xml~). 여러 번 지정 가능."
    )
    parser.add_argument("--title")
    parser.add_argument("--creator")
    parser.add_argument("--output", "-o", type=Path, required=True)
    args = parser.parse_args()

    build(
        template=args.template,
        header_override=args.header,
        section_override=args.section,
        extra_sections=args.extra_sections,
        title=args.title,
        creator=args.creator,
        output=args.output,
    )


if __name__ == "__main__":
    main()
