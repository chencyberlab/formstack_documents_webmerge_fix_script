"""
WebMerge docx checker/fixer (debugging tool)

Detects and repairs the Formstack WebMerge corruption signature:
  '</w:t><w:br/><w:t>' injected into package XML files.

This script scans EVERY file inside the .docx ZIP (not just [Content_Types].xml)
so it will surface the corruption wherever it occurs.

The source file is NEVER modified. A new file is always written on fix.

Usage:
    python fix_webmerge.py <input.docx>
        -> checks; if corrupted, writes <input>.fixed.docx alongside source

    python fix_webmerge.py <input.docx> <output.docx>
        -> checks; if corrupted, writes to the given output path

    python fix_webmerge.py --check <input.docx>
        -> check only, do not write anything

    python fix_webmerge.py --debug <input.docx>
        -> write a detailed debug report (<input>.debug.txt):
           full ZIP listing, every affected file with full content, hex dumps,
           and byte-level context for every occurrence found.
           Can be combined with other modes.

Exit codes:
    0  clean (or --check and clean)
    1  corrupted (fixed file written, unless --check)
    2  usage error
    3  file error (missing, not a docx, etc)
"""

import shutil
import sys
import traceback
import zipfile
from pathlib import Path

SIGNATURE = '</w:t><w:br/><w:t>'
CT_PATH = '[Content_Types].xml'


# --- ANSI colors (disabled if stdout isn't a tty) ---------------------------

_tty = sys.stdout.isatty()
def _c(code, s):
    return f'\033[{code}m{s}\033[0m' if _tty else s
def RED(s):    return _c('31', s)
def GREEN(s):  return _c('32', s)
def YELLOW(s): return _c('33', s)
def BOLD(s):   return _c('1',  s)
def DIM(s):    return _c('2',  s)


def log_info(label, value=''):
    print(f'  {label:<22} {value}')

def log_ok(msg):
    print(f'  {GREEN("[OK]")} {msg}')

def log_warn(msg):
    print(f'  {YELLOW("[!]")} {msg}')

def log_err(msg):
    print(f'  {RED("[ERROR]")} {msg}', file=sys.stderr)


# --- core -------------------------------------------------------------------

class DocxError(Exception):
    """Raised for expected docx-level errors (not a zip, missing part, etc)."""


def _find_all_offsets(text: str, needle: str) -> list:
    """Return every offset at which needle occurs in text."""
    offsets = []
    pos = 0
    while True:
        p = text.find(needle, pos)
        if p < 0:
            break
        offsets.append(p)
        pos = p + 1
    return offsets


def inspect(input_path: Path) -> dict:
    """Open the docx and scan every file inside for the signature.

    Returns a diagnostics dict including a per-file breakdown of occurrences.
    Raises DocxError on failure.
    """
    if not input_path.exists():
        raise DocxError(f'file not found: {input_path}')
    if not input_path.is_file():
        raise DocxError(f'not a file: {input_path}')

    size = input_path.stat().st_size
    if size == 0:
        raise DocxError('file is empty (0 bytes)')

    try:
        with zipfile.ZipFile(input_path, 'r') as z:
            bad = z.testzip()
            if bad is not None:
                raise DocxError(f'ZIP integrity check failed on entry: {bad}')
            names = z.namelist()
            if CT_PATH not in names:
                raise DocxError(f'missing {CT_PATH} (not a valid .docx)')
            if 'word/document.xml' not in names:
                raise DocxError('missing word/document.xml (not a Word document)')

            # read every entry once; decode text-like entries so we can search them
            entries = []
            for info in z.infolist():
                raw = z.read(info.filename)
                # we consider anything we can decode as UTF-8 as text-searchable;
                # binary entries (images, oleObject .bin, etc.) are not searched
                is_text = False
                text = None
                try:
                    text = raw.decode('utf-8')
                    is_text = True
                except UnicodeDecodeError:
                    pass

                occurrences = text.count(SIGNATURE) if is_text else 0
                offsets = _find_all_offsets(text, SIGNATURE) if occurrences else []

                entries.append({
                    'name': info.filename,
                    'info': info,
                    'raw': raw,
                    'text': text,          # None if binary
                    'is_text': is_text,
                    'occurrences': occurrences,
                    'offsets': offsets,
                })
    except zipfile.BadZipFile as e:
        raise DocxError(f'not a valid ZIP archive: {e}')

    affected = [e for e in entries if e['occurrences'] > 0]
    total_occurrences = sum(e['occurrences'] for e in entries)

    return {
        'path': input_path,
        'size': size,
        'entries': entries,
        'entry_count': len(entries),
        'affected': affected,
        'affected_count': len(affected),
        'total_occurrences': total_occurrences,
        'corrupted': total_occurrences > 0,
    }


def write_fixed(diag: dict, output_path: Path) -> dict:
    """Write a repaired copy. Replaces SIGNATURE in every affected text entry.

    Returns {'files': int, 'occurrences': int} summarizing what was repaired.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + '.tmp')

    files_fixed = 0
    occurrences_fixed = 0
    try:
        with zipfile.ZipFile(diag['path'], 'r') as zin, \
             zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for entry in diag['entries']:
                if entry['occurrences'] > 0:
                    fixed_text = entry['text'].replace(SIGNATURE, '\n')
                    zout.writestr(entry['info'], fixed_text.encode('utf-8'))
                    files_fixed += 1
                    occurrences_fixed += entry['occurrences']
                else:
                    # pass through untouched (works for binary too because we have raw bytes)
                    zout.writestr(entry['info'], entry['raw'])
        shutil.move(str(tmp), str(output_path))
    except Exception:
        if tmp.exists():
            try: tmp.unlink()
            except OSError: pass
        raise

    return {'files': files_fixed, 'occurrences': occurrences_fixed}


def _hexdump(data: bytes, start_offset: int = 0) -> str:
    """Produce a classic hex+ASCII dump of bytes, 16 per line."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        hex_part = hex_part.ljust(48)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'  {start_offset + i:08x}  {hex_part}  |{ascii_part}|')
    return '\n'.join(lines)


def build_debug_report(diag: dict) -> str:
    """Produce a detailed text report about the docx and any corruption found."""
    from datetime import datetime, timezone

    lines = []
    w = lines.append

    w('=' * 78)
    w('WEBMERGE DOCX DEBUG REPORT')
    w('=' * 78)
    w(f'Generated:         {datetime.now(timezone.utc).isoformat()}')
    w(f'File:              {diag["path"]}')
    w(f'Size:              {diag["size"]:,} bytes')
    w(f'Status:            {"CORRUPTED" if diag["corrupted"] else "CLEAN"}')
    w(f'Files scanned:     {diag["entry_count"]}')
    w(f'Files affected:    {diag["affected_count"]}')
    w(f'Total occurrences: {diag["total_occurrences"]}')
    w(f'Signature:         {SIGNATURE!r}')
    w('')

    # ZIP inventory with per-file occurrence counts
    w('-' * 78)
    w('ZIP CONTENTS (annotated with corruption signature occurrences)')
    w('-' * 78)
    w(f'{"Size":>10}  {"Compressed":>10}  {"Modified":<20}  {"Hits":>4}  Name')
    for e in diag['entries']:
        info = e['info']
        mtime = '%04d-%02d-%02d %02d:%02d:%02d' % info.date_time
        if e['occurrences'] > 0:
            hits = f'{e["occurrences"]:>4}'
            marker = '*'
        elif not e['is_text']:
            hits = ' bin'
            marker = ' '
        else:
            hits = '   0'
            marker = ' '
        w(f'{info.file_size:>10,}  {info.compress_size:>10,}  {mtime:<20}  '
          f'{hits}{marker} {info.filename}')
    w('')
    w('  * = file contains the corruption signature')
    w('  bin = binary file (not searched; images, embedded objects, etc.)')
    w('')

    # Detail for each affected file
    if diag['affected']:
        w('=' * 78)
        w('AFFECTED FILES - DETAILS')
        w('=' * 78)
        w('')

        for idx, entry in enumerate(diag['affected'], 1):
            text = entry['text']
            raw = entry['raw']
            name = entry['name']

            w('#' * 78)
            w(f'# AFFECTED FILE {idx}/{len(diag["affected"])}: {name}')
            w('#' * 78)
            w(f'Content length:    {len(raw):,} bytes')
            w(f'Occurrences:       {entry["occurrences"]}')
            w(f'All offsets:       {entry["offsets"]}')
            w('')

            # Per-occurrence context
            for occ_idx, offset in enumerate(entry['offsets'], 1):
                w('-' * 78)
                w(f'Occurrence {occ_idx}/{entry["occurrences"]} at byte offset {offset}')
                w('-' * 78)
                sig_len = len(SIGNATURE)
                ctx_before = 100
                ctx_after = 100
                start = max(0, offset - ctx_before)
                end = min(len(text), offset + sig_len + ctx_after)
                before = text[start:offset]
                after = text[offset + sig_len:end]

                w('Text context:')
                w('  -- before --')
                w(f'  {before!r}')
                w('  -- corruption --')
                w(f'  {SIGNATURE!r}')
                w('  -- after --')
                w(f'  {after!r}')
                w('')

                byte_start = max(0, offset - 32)
                byte_end = min(len(raw), offset + sig_len + 32)
                w(f'Hex dump of corruption region (bytes {byte_start}-{byte_end}):')
                w(_hexdump(raw[byte_start:byte_end], start_offset=byte_start))
                w('')

            # Full content of the affected file (with size guard so the report
            # doesn't explode on very large parts like word/styles.xml if that
            # ever gets corrupted)
            MAX_FULL_DUMP = 200_000  # 200 KB
            if len(text) <= MAX_FULL_DUMP:
                w('-' * 78)
                w(f'FULL CONTENT OF {name} ({len(raw):,} bytes)')
                w('-' * 78)
                w(text)
                if not text.endswith('\n'):
                    w('')
            else:
                # show the head of the file (covers the typical corruption location)
                w('-' * 78)
                w(f'FIRST {MAX_FULL_DUMP:,} BYTES OF {name} '
                  f'(total: {len(raw):,} bytes - truncated)')
                w('-' * 78)
                w(text[:MAX_FULL_DUMP])
                w('')
                w(f'... [truncated, {len(text) - MAX_FULL_DUMP:,} more chars] ...')
                w('')

            # first 256 bytes hex
            w('-' * 78)
            w(f'FIRST 256 BYTES OF {name} (hex)')
            w('-' * 78)
            w(_hexdump(raw[:256]))
            w('')

            # summary of fix action
            fixed = text.replace(SIGNATURE, '\n')
            w('-' * 78)
            w('Fix action for this file:')
            w(f'  replace {SIGNATURE!r} with {chr(10)!r} (newline)')
            w(f'  size change: {len(raw):,} -> {len(fixed.encode("utf-8")):,} bytes')
            w('')
    else:
        w('-' * 78)
        w('No files contain the corruption signature.')
        w('-' * 78)
        w('')

    w('=' * 78)
    w('END OF REPORT')
    w('=' * 78)

    return '\n'.join(lines)


# --- cli --------------------------------------------------------------------

def print_diagnostics(diag: dict):
    print(BOLD('Inspection'))
    log_info('Path:',           diag['path'])
    log_info('Size:',            f"{diag['size']:,} bytes")
    log_info('Files in ZIP:',    f"{diag['entry_count']}")

    if diag['corrupted']:
        print()
        print(RED(BOLD('CORRUPTED')))
        log_info('Signature:',         repr(SIGNATURE))
        log_info('Files affected:',    diag['affected_count'])
        log_info('Total occurrences:', diag['total_occurrences'])
        print()
        print(f'  {BOLD("Per-file breakdown:")}')
        for e in diag['affected']:
            offsets_str = ', '.join(str(o) for o in e['offsets'])
            print(f'    {RED("*")} {e["name"]}: {e["occurrences"]} '
                  f'occurrence(s) at byte offset(s) [{offsets_str}]')
    else:
        print()
        print(GREEN(BOLD('CLEAN')) + ' - no corruption signature found in any file')


def main(argv):
    args = argv[1:]
    check_only = False
    debug = False

    # parse flags (order-independent)
    remaining = []
    for a in args:
        if a == '--check':
            check_only = True
        elif a == '--debug':
            debug = True
        elif a.startswith('-'):
            log_err(f'unknown flag: {a}')
            return 2
        else:
            remaining.append(a)
    args = remaining

    if len(args) < 1 or len(args) > 2:
        print(__doc__)
        return 2

    input_path = Path(args[0]).resolve()
    output_path = Path(args[1]).resolve() if len(args) == 2 else None

    # inspect
    try:
        diag = inspect(input_path)
    except DocxError as e:
        log_err(str(e))
        return 3
    except Exception as e:
        log_err(f'unexpected error while inspecting: {e.__class__.__name__}: {e}')
        if sys.stderr.isatty():
            traceback.print_exc(file=sys.stderr)
        return 3

    print_diagnostics(diag)

    # debug report (works for both clean and corrupted files)
    if debug:
        print()
        print(BOLD('Debug report'))
        report_path = input_path.with_name(f'{input_path.stem}.debug.txt')
        try:
            report = build_debug_report(diag)
            report_path.write_text(report, encoding='utf-8')
            log_ok(f'wrote {report_path} ({report_path.stat().st_size:,} bytes)')
        except Exception as e:
            log_err(f'failed to write debug report: {e}')

    if not diag['corrupted']:
        return 0

    if check_only:
        print()
        log_warn('--check specified: no fixed file written')
        return 1

    # decide output path; never clobber the source
    out = output_path or input_path.with_name(f'{input_path.stem}.fixed{input_path.suffix}')
    if out.resolve() == input_path.resolve():
        log_err(f'refusing to overwrite source file: {out}')
        return 3

    print()
    print(BOLD('Repair'))
    try:
        result = write_fixed(diag, out)
    except PermissionError as e:
        log_err(f'cannot write to {out}: {e}')
        return 3
    except OSError as e:
        log_err(f'OS error writing to {out}: {e}')
        return 3
    except Exception as e:
        log_err(f'unexpected error while writing: {e.__class__.__name__}: {e}')
        if sys.stderr.isatty():
            traceback.print_exc(file=sys.stderr)
        return 3

    log_ok(f'repaired {result["occurrences"]} occurrence(s) across {result["files"]} file(s)')
    log_ok(f'wrote {out} ({out.stat().st_size:,} bytes)')
    log_info('Source:', f"{input_path} (unchanged)")
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))