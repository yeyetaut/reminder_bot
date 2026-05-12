import logging
import base64
from io import BytesIO
from typing import Optional
import anthropic

import config

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
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
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

def extract_text_with_ai(file_bytes: bytes) -> Optional[str]:
    """Fallback mechanism using AI Vision to extract text from a scanned document/PDF."""
    if not config.ANTHROPIC_API_KEY:
        logger.error("Anthropic API key is not configured.")
        return None

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        base64_data = base64.b64encode(file_bytes).decode("utf-8")
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64_data
                            }
                        },
                        {
                            "type": "text",
                            "text": "Please extract all the text from this document exactly as it appears. If it is a rubric or syllabus, preserve the logical structure."
                        }
                    ]
                }
            ]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Error extracting text with AI Vision: {e}")
        return None
