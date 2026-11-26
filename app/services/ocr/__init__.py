"""OCR (Optical Character Recognition) extraction service.

Extracts text from documents and images using multiple backends:
- PDFs: embedded text extraction with PyMuPDF/pdfplumber, OCR fallback via GLM-ocr
- Images: vision-model OCR via GLM-ocr

The dispatcher (extractor.py) routes files to the correct handler
based on MIME type.
"""
