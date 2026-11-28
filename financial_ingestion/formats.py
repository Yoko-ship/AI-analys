"""Identify source bytes and render supported documents for the page parser."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import warnings
import zipfile

import olefile
from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

VERSION = 'document-render-v1'
MEDIA_TYPES = {
    'pdf': 'application/pdf',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'jpg': 'image/jpeg',
    'png': 'image/png',
    'tiff': 'image/tiff',
}
EXTENSIONS = (*(kind for kind in MEDIA_TYPES if kind != 'xlsx'), 'jpeg', 'tif')
MAX_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_IMAGE_PAGES = 32


def identify(payload):
    """File names and HTTP content types are hints, never format evidence."""
    if payload.startswith(b'%PDF-'):
        return 'pdf'
    if payload.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_BYTES:
                    raise ValueError('Word archive exceeds expanded size limit')
                names = {e.filename for e in entries}
                if 'xl/workbook.xml' in names:
                    from .workbooks import check_package
                    check_package(payload)
                    return 'xlsx'
                if {'[Content_Types].xml', 'word/document.xml'} <= names:
                    return 'docx'
        except zipfile.BadZipFile as exc:
            raise ValueError('Invalid Word archive') from exc
    if payload.startswith(olefile.MAGIC):
        try:
            with olefile.OleFileIO(io.BytesIO(payload)) as document:
                if document.exists('WordDocument'):
                    return 'doc'
        except (OSError, ValueError) as exc:
            raise ValueError('Invalid Word compound document') from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                kind = {'JPEG': 'jpg', 'PNG': 'png', 'TIFF': 'tiff'}.get(image.format)
                if kind:
                    _check_image(image)
                    image.verify()
                    return kind
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('Unsupported or invalid source document') from exc
    raise ValueError('Unsupported source document format')


def to_pdf(payload, kind):
    if kind == 'pdf':
        return payload
    if kind in {'jpg', 'png', 'tiff'}:
        return _image_pdf(payload)
    if kind in {'doc', 'docx'}:
        return _word_pdf(payload, kind)
    raise ValueError('Unsupported source document format')


def _check_image(image):
    if image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) > MAX_IMAGE_PAGES:
        raise ValueError('Source image exceeds pixel/page limit')


def _image_pdf(payload):
    output = io.BytesIO()
    pdf = canvas.Canvas(output, invariant=True)
    with Image.open(io.BytesIO(payload)) as image:
        _check_image(image)
        for number in range(getattr(image, 'n_frames', 1)):
            image.seek(number)
            _check_image(image)
            page = ImageOps.exif_transpose(image).convert('RGB')
            # Keep all pixels, but give scans a normal page size for bounded OCR.
            width, height = page.size
            scale = 842 / max(width, height)
            size = width * scale, height * scale
            pdf.setPageSize(size)
            pdf.drawImage(ImageReader(page), 0, 0, width=size[0], height=size[1])
            pdf.showPage()
    pdf.save()
    result = output.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError('Rendered PDF exceeds size limit')
    return result


def _word_pdf(payload, kind):
    executable = os.environ.get('LIBREOFFICE_BINARY') or shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('WORD_CONVERTER_UNAVAILABLE: install LibreOffice Writer')
    with tempfile.TemporaryDirectory(prefix='financial-word-') as scratch:
        root = Path(scratch)
        profile = root / 'profile' / 'user'
        profile.mkdir(parents=True)
        (profile / 'registrymodifications.xcu').write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>'
            '<item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>'
            '</oor:items>', encoding='utf-8')
        source = root / ('source.' + kind)
        source.write_bytes(payload)
        try:
            subprocess.run([executable, '-env:UserInstallation=' + profile.parent.as_uri(),
                            '--headless', '--nologo', '--nodefault', '--norestore',
                            '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(root), str(source)],
                           cwd=root, capture_output=True, timeout=120, check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('WORD_CONVERSION_TIMEOUT') from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError('WORD_CONVERSION_FAILED') from exc
        result = root / 'source.pdf'
        if not result.exists() or result.stat().st_size > MAX_BYTES:
            raise ValueError('Word conversion produced no PDF or exceeded size limit')
        content = result.read_bytes()
        if not content.startswith(b'%PDF-'):
            raise ValueError('Word conversion produced invalid PDF')
        return content
