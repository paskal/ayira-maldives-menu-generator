import base64
import io
import string
import zipfile
from pathlib import Path

import pytest

import generate_menu as gm

ROOT = Path(__file__).resolve().parent.parent

PNG_BYTES = b'\x89PNG\r\n\x1a\nfake-png'
JPG_BYTES = b'\xff\xd8\xfffake-jpg'


def cell(value: str) -> dict:
    return {'formattedValue': value} if value else {}


def row(*values: str) -> dict:
    return {'values': [cell(v) for v in values]}


# --- XLSX fixtures -----------------------------------------------------------

def rels(*entries: tuple[str, str, str]) -> str:
    body = ''.join(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" '
        f'Target="{target}"/>'
        for rid, kind, target in entries
    )
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def anchor(kind: str, row_idx: int, col: int, rid: str) -> str:
    return (
        f'<xdr:{kind}><xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff>'
        f'<xdr:row>{row_idx}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        f'<xdr:pic><xdr:blipFill><a:blip r:embed="{rid}"/></xdr:blipFill></xdr:pic></xdr:{kind}>'
    )


def drawing(*anchors: str) -> str:
    return (
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        + ''.join(anchors) + '</xdr:wsDr>'
    )


def build_xlsx() -> bytes:
    """Two tabs: 'Drinks' first with one photo, 'Food menu' second with a logo and photos."""
    files = {
        'xl/workbook.xml': (
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Drinks" sheetId="1" r:id="rId1"/>'
            '<sheet name="Food menu" sheetId="2" r:id="rId2"/>'
            '</sheets></workbook>'
        ),
        'xl/_rels/workbook.xml.rels': rels(
            ('rId1', 'worksheet', 'worksheets/sheet1.xml'),
            ('rId2', 'worksheet', '/xl/worksheets/sheet2.xml'),
        ),
        'xl/worksheets/sheet1.xml': '<worksheet/>',
        'xl/worksheets/sheet2.xml': '<worksheet/>',
        'xl/worksheets/_rels/sheet1.xml.rels': rels(('rId1', 'drawing', '../drawings/drawing1.xml')),
        'xl/worksheets/_rels/sheet2.xml.rels': rels(('rId1', 'drawing', '../drawings/drawing2.xml')),
        'xl/drawings/drawing1.xml': drawing(anchor('oneCellAnchor', 1, 4, 'rId1')),
        'xl/drawings/_rels/drawing1.xml.rels': rels(('rId1', 'image', '../media/image1.jpg')),
        'xl/drawings/drawing2.xml': drawing(
            anchor('oneCellAnchor', 1, 6, 'rId1'),
            anchor('twoCellAnchor', 3, 4, 'rId2'),
        ),
        'xl/drawings/_rels/drawing2.xml.rels': rels(
            ('rId1', 'image', '../media/image2.png'),
            ('rId2', 'image', '../media/image3.JPEG'),
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, text in files.items():
            zf.writestr(name, text)
        zf.writestr('xl/media/image1.jpg', JPG_BYTES)
        zf.writestr('xl/media/image2.png', PNG_BYTES)
        zf.writestr('xl/media/image3.JPEG', JPG_BYTES)
    return buf.getvalue()


def data_uri(mime: str, payload: bytes) -> str:
    return f'data:image/{mime};base64,{base64.b64encode(payload).decode("ascii")}'


# --- images_from_xlsx --------------------------------------------------------

def test_images_come_from_the_selected_tab():
    images = gm.images_from_xlsx(build_xlsx(), 'Food menu')
    assert images == {
        (1, 6): data_uri('png', PNG_BYTES),
        (3, 4): data_uri('jpeg', JPG_BYTES),
    }


def test_empty_tab_title_selects_the_first_tab(caplog):
    assert gm.images_from_xlsx(build_xlsx(), '') == {(1, 4): data_uri('jpeg', JPG_BYTES)}
    assert caplog.records == []


def test_unknown_tab_title_yields_no_images(caplog):
    assert gm.images_from_xlsx(build_xlsx(), 'No such tab') == {}
    assert [r.getMessage() for r in caplog.records] == [
        "Tab 'No such tab' not found in the XLSX export, skipping images",
    ]


def test_tab_without_drawing_gets_no_images_from_another_tab():
    files = {}
    with zipfile.ZipFile(io.BytesIO(build_xlsx())) as zf:
        for name in zf.namelist():
            files[name] = zf.read(name)
    # Second tab loses its drawing; the first tab keeps its photo
    del files['xl/worksheets/_rels/sheet2.xml.rels']
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    assert gm.images_from_xlsx(buf.getvalue(), 'Drinks') == {(1, 4): data_uri('jpeg', JPG_BYTES)}
    assert gm.images_from_xlsx(buf.getvalue(), 'Food menu') == {}


# --- configuration and ranges ------------------------------------------------

@pytest.mark.parametrize('env_value', [None, '', '  '])
def test_missing_or_empty_sheet_name_selects_first_tab(monkeypatch, env_value):
    monkeypatch.setenv('SPREADSHEET_ID', 'id')
    monkeypatch.setenv('GCP_CREDS_JSON', '{}')
    if env_value is None:
        monkeypatch.delenv('SHEET_NAME', raising=False)
    else:
        monkeypatch.setenv('SHEET_NAME', env_value)
    _, sheet_name, _ = gm.get_config()
    assert sheet_name == ''
    assert gm.sheet_ranges(sheet_name) == ['A2:E', 'H2']


def test_sheet_name_is_quoted_in_ranges():
    assert gm.sheet_ranges("Chef's menu") == ["'Chef''s menu'!A2:E", "'Chef''s menu'!H2"]


class FakeSheets:
    def __init__(self, response: dict):
        self.response = response
        self.kwargs: dict = {}

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self.kwargs = kwargs
        return self

    def execute(self):
        return self.response


def test_get_sheet_data_returns_tab_title_menu_title_and_rows():
    rows = [row('Soup', '5', 'Starters')]
    service = FakeSheets({'sheets': [{
        'properties': {'title': 'Food menu'},
        'data': [{'rowData': rows}, {'rowData': [row('Dinner')]}],
    }]})
    assert gm.get_sheet_data(service, 'id', 'Food menu') == ('Food menu', 'Dinner', rows)
    assert service.kwargs['ranges'] == ["'Food menu'!A2:E", "'Food menu'!H2"]


def test_get_sheet_data_defaults_menu_title():
    service = FakeSheets({'sheets': [{'properties': {'title': 'Sheet1'}, 'data': [{}, {}]}]})
    assert gm.get_sheet_data(service, 'id', '') == ('Sheet1', 'Restaurant Menu', [])


# --- process_menu_items ------------------------------------------------------

def test_rows_are_grouped_by_category_with_photos_by_row():
    values = [
        row('Soup', '5', 'Starters', 'Hot'),
        row('Fish', '12', 'Mains'),
        row('Salad', '6', 'Starters'),
    ]
    images = {(2, 4): 'data:image/png;base64,AA=='}
    menu = gm.process_menu_items(values, images)
    assert list(menu) == ['Starters', 'Mains']
    assert [item['title'] for item in menu['Starters']] == ['Soup', 'Salad']
    assert menu['Starters'][0]['description'] == 'Hot'
    assert menu['Mains'][0]['image_src'] == 'data:image/png;base64,AA=='
    assert menu['Starters'][0]['image_src'] == ''


def test_incomplete_rows_are_skipped_with_a_warning(caplog):
    values = [
        {},
        row('Water', '1'),
        row('', '2', 'Drinks'),
        row(' ', '2', 'Drinks'),
        row('Tea', '2', '  '),
        row('Juice', '3', 'Drinks'),
    ]
    menu = gm.process_menu_items(values, {})
    assert menu == {'Drinks': [{'title': 'Juice', 'price': '3', 'description': '', 'image_src': ''}]}
    assert [r.getMessage() for r in caplog.records] == [
        'Skipping sheet row 3: it needs both a title and a category',
        'Skipping sheet row 4: it needs both a title and a category',
        'Skipping sheet row 5: it needs both a title and a category',
        'Skipping sheet row 6: it needs both a title and a category',
    ]


# --- generate_html -----------------------------------------------------------

def render(menu: gm.MenuData, title: str = 'Menu') -> str:
    return gm.generate_html(gm.load_template(), menu, title, 'data:image/png;base64,AA==')


def item(title: str = 'Dish', description: str = '', image_src: str = '') -> gm.MenuItem:
    return {'title': title, 'price': '10', 'description': description, 'image_src': image_src}


def test_sheet_text_is_escaped():
    out = render({'<b>Cat</b>': [item(title='<script>x</script>', description='"a" & b')]}, title='A & B')
    assert '<title>A &amp; B</title>' in out
    assert '&lt;b&gt;Cat&lt;/b&gt;' in out
    assert '&lt;script&gt;x&lt;/script&gt;' in out
    assert '<script>x</script>' not in out
    assert '&quot;a&quot; &amp; b' in out
    assert 'data-full-description="&quot;a&quot; &amp; b"' in out
    # Each value appears in several places; the raw form must be absent from all of them
    for raw in ('A & B', '<b>Cat</b>', '"a" & b'):
        assert raw not in out


def test_quotes_cannot_close_an_attribute():
    dish = item(title='Fish "special"', image_src='data:image/png;base64,AA==')
    out = render({'Mains': [dish]}, title='Chez "Nous"')
    assert 'alt="Fish &quot;special&quot;"' in out
    assert 'alt="Chez &quot;Nous&quot; logo"' in out
    assert 'special"' not in out
    assert 'Nous"' not in out


def test_long_description_is_cut_before_escaping():
    description = 'x' * 79 + '& more text that runs past the limit'
    out = render({'Mains': [item(description=description)]})
    assert 'x' * 79 + '&amp;...' in out
    assert '&am...' not in out
    assert '>More</button>' in out
    assert f'data-full-description="{"x" * 79}&amp; more text that runs past the limit"' in out


def test_description_of_80_characters_is_not_cut_even_when_escaping_lengthens_it():
    description = 'y' * 79 + '&'
    out = render({'Mains': [item(description=description)]})
    assert '>More</button>' not in out
    assert '...' not in out
    assert 'y' * 79 + '&amp;\n' in out


def test_template_placeholders_are_all_filled():
    out = render({'Mains': [item(image_src='data:image/png;base64,AA==')]})
    placeholders = {
        m.group('named') or m.group('braced')
        for m in string.Template.pattern.finditer((ROOT / 'template.html').read_text())
        if m.group('named') or m.group('braced')
    }
    assert placeholders == {'title', 'logo_src', 'categories', 'menu_items'}
    for name in placeholders:
        assert f'${name}' not in out
        assert f'${{{name}}}' not in out
