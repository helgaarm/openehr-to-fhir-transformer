import textwrap
from typing import Iterable, List


def build_text_pdf(title: str, lines: Iterable[str]) -> bytes:
    """Build a small single-font PDF from plain text lines."""
    page_width = 595
    page_height = 842
    margin_left = 50
    start_y = 790
    line_height = 14
    lines_per_page = 52

    wrapped_lines: List[str] = []
    wrapped_lines.append(title)
    wrapped_lines.append('')
    for line in lines:
        if not line:
            wrapped_lines.append('')
            continue
        wrapped_lines.extend(textwrap.wrap(str(line), width=92) or [''])

    pages = [
        wrapped_lines[index:index + lines_per_page]
        for index in range(0, len(wrapped_lines), lines_per_page)
    ] or [[title]]

    objects: List[bytes] = []

    def add_object(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    catalog_id = add_object(b'')
    pages_id = add_object(b'')
    font_id = add_object(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    page_ids: List[int] = []

    for page_lines in pages:
        content_stream = _page_content_stream(
            page_lines,
            margin_left=margin_left,
            start_y=start_y,
            line_height=line_height,
        )
        content_id = add_object(
            b'<< /Length ' + str(len(content_stream)).encode('ascii') + b' >>\nstream\n'
            + content_stream
            + b'\nendstream'
        )
        page_id = add_object(
            (
                f'<< /Type /Page /Parent {pages_id} 0 R '
                f'/MediaBox [0 0 {page_width} {page_height}] '
                f'/Resources << /Font << /F1 {font_id} 0 R >> >> '
                f'/Contents {content_id} 0 R >>'
            ).encode('ascii')
        )
        page_ids.append(page_id)

    objects[catalog_id - 1] = f'<< /Type /Catalog /Pages {pages_id} 0 R >>'.encode('ascii')
    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    objects[pages_id - 1] = f'<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>'.encode('ascii')

    return _assemble_pdf(objects)


def _page_content_stream(
    lines: List[str],
    margin_left: int,
    start_y: int,
    line_height: int,
) -> bytes:
    commands = ['BT', '/F1 10 Tf', '12 TL']
    y = start_y

    for index, line in enumerate(lines):
        font_size = 16 if index == 0 else 10
        commands.append(f'/F1 {font_size} Tf')
        commands.append(f'1 0 0 1 {margin_left} {y} Tm')
        commands.append(f'<{_pdf_utf16_hex(line)}> Tj')
        y -= line_height + (6 if index == 0 else 0)

    commands.append('ET')
    return '\n'.join(commands).encode('ascii')


def _pdf_utf16_hex(text: str) -> str:
    normalized = text.replace('\r', ' ').replace('\n', ' ')
    return (b'\xfe\xff' + normalized.encode('utf-16-be')).hex().upper()


def _assemble_pdf(objects: List[bytes]) -> bytes:
    output = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f'{index} 0 obj\n'.encode('ascii'))
        output.extend(obj)
        output.extend(b'\nendobj\n')

    xref_offset = len(output)
    output.extend(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    output.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))

    output.extend(
        (
            f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref_offset}\n%%EOF\n'
        ).encode('ascii')
    )
    return bytes(output)
