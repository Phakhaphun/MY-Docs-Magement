# OCR language assets

Docspace uses the Tesseract OCR engine included in the installed PyMuPDF wheel,
with the official integer `tessdata_fast` models. No CUDA, GPU framework, system
Tesseract executable or Ghostscript is required by this implementation.

- Source: https://github.com/tesseract-ocr/tessdata_fast
- Pinned revision: `87416418657359cb625c412a48b6e1d6d41c29bd`
- License: Apache 2.0, copied in `LICENSE-tessdata_fast.txt`.
- Bundled models: `tessdata/eng.traineddata`, `tessdata/tha.traineddata`.
- `manifest.json` records the size and Git blob SHA-1 of each optional model.

The app downloads optional models only when the user clicks **Download languages**.
Downloads use the pinned official raw GitHub URL and are checked against the
manifest before an atomic rename. No document data is included in these requests.
Models stay in `tessdata/` for subsequent offline use. Optional downloaded models
are ignored by Git; copy their files as well when moving an offline installation.

The 123 catalog entries include historical and vertical-writing model variants;
this is a model count, not 123 independently tested modern languages. The deprecated
`frk` symlink alias and non-language `equ`/`osd` detectors are excluded. English and
Thai recognition and a French pack download have been exercised on this Windows
x64 development machine. Other languages are supported by their upstream models,
but have not each undergone an accuracy evaluation here.
