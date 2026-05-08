import logging
from io import BytesIO
from typing import Optional

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_bytes: bytes) -> Optional[str]:
    """Extract text from a PDF file."""
    if not PdfReader:
        logger.error("pypdf not installed")
        return None
    
    try:
        reader = PdfReader(BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        return None

def extract_text_from_docx(file_bytes: bytes) -> Optional[str]:
    """Extract text from a Word document."""
    if not Document:
        logger.error("python-docx not installed")
        return None
    
    try:
        doc = Document(BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs])
        return text.strip()
    except Exception as e:
        logger.error(f"Error extracting text from Word: {e}")
        return None
