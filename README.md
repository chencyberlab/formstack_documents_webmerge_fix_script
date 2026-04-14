# DocFix -- WebMerge DOCX Checker & Fixer

A lightweight debugging tool to **detect and repair corrupted `.docx`
files** caused by Formstack WebMerge.
This can only help to fix the corrupted file but unable to hijack the "Merge" or "Delivery" process, thus no way to fix the file before generating the doc or sending for signing.

## 🚨 What problem does this solve?

Some WebMerge-generated `.docx` files contain a corruption pattern:

    </w:t><w:br/><w:t>

This breaks the internal XML structure of the Word document and can
cause: - Word failing to open the file - Formatting issues - Downstream
processing errors

This tool: - 🔍 Scans **every file inside the DOCX (ZIP)**\
- 🧠 Detects corruption anywhere (not just common locations)\
- 🔧 Fixes it safely by replacing the corrupted pattern with a newline

------------------------------------------------------------------------

## ✨ Features

-   Full ZIP-level inspection of `.docx` files\
-   Detects all occurrences of the corruption signature\
-   Safe fix (never modifies the original file)\
-   Detailed debug reports (with byte-level analysis)\
-   Clear CLI output with per-file breakdown

------------------------------------------------------------------------

## 📦 Installation

No external dependencies required. Just Python 3:

``` bash
python DocFix.py
```

------------------------------------------------------------------------

## 🚀 Usage

### 1. Check and auto-fix (default)

``` bash
python DocFix.py input.docx
```

-   If corrupted → creates:

        input.fixed.docx

-   If clean → no file created

------------------------------------------------------------------------

### 2. Specify output file

``` bash
python DocFix.py input.docx output.docx
```

------------------------------------------------------------------------

### 3. Check only (no changes)

``` bash
python DocFix.py --check input.docx
```

------------------------------------------------------------------------

### 4. Generate debug report

``` bash
python DocFix.py --debug input.docx
```

Creates:

    input.debug.txt

Includes: - Full ZIP structure - Affected files - Exact byte offsets -
Hex dumps - Context around corruption

------------------------------------------------------------------------

### 5. Combine modes

``` bash
python DocFix.py --check --debug input.docx
```

------------------------------------------------------------------------

## 🛠 How it works

1.  Opens `.docx` as a ZIP archive\

2.  Scans all text-based files inside\

3.  Detects occurrences of:

        </w:t><w:br/><w:t>

4.  If fixing:

    -   Replaces with `\n` (newline)
    -   Rebuilds a clean `.docx`
    -   Leaves original untouched

------------------------------------------------------------------------

## 📊 Exit Codes

  Code   Meaning
  ------ ----------------------------------------------
  0      Clean (no corruption)
  1      Corrupted (fixed or detected with `--check`)
  2      Usage error
  3      File/system error

------------------------------------------------------------------------

## ⚠️ Safety

-   ✅ Original file is **never modified**
-   ✅ Fix is applied only to affected XML entries
-   ✅ Binary files (images, etc.) are untouched

------------------------------------------------------------------------

## 🧪 Example Output

    CORRUPTED
      Signature: '</w:t><w:br/><w:t>'
      Files affected: 2
      Total occurrences: 5

    Repair
      [OK] repaired 5 occurrence(s) across 2 file(s)
      [OK] wrote input.fixed.docx

------------------------------------------------------------------------

## 📄 License

Use freely for debugging and internal tooling.
