from typing import Dict, Any
from pathlib import Path
import base64
import io

try:
    from PIL import Image
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

def image_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process images: extract text using OCR, analyze image properties.
    Supports base64-encoded images or file paths.
    """
    image_input = arguments.get("image", "")
    query = arguments.get("query", "")
    
    if not HAS_OCR:
        return {
            "error": "Image processing libraries not installed. Install Pillow and pytesseract.",
            "requires": ["Pillow", "pytesseract"]
        }
    
    try:
        # Try to load from base64
        if image_input.startswith("data:image"):
            header, data = image_input.split(",")
            image_bytes = base64.b64decode(data)
            img = Image.open(io.BytesIO(image_bytes))
        else:
            # Try to load from file path
            path = Path(image_input)
            if path.exists():
                img = Image.open(path)
            else:
                return {
                    "error": f"Image file not found: {image_input}",
                    "supported_formats": ["PNG", "JPG", "JPEG", "GIF", "BMP", "TIFF"]
                }
        
        # Extract text using OCR
        text = pytesseract.image_to_string(img)
        
        # Get image properties
        width, height = img.size
        image_format = img.format or "unknown"
        
        result = {
            "success": True,
            "image_path": str(image_input),
            "image_format": image_format,
            "width": width,
            "height": height,
            "extracted_text": text.strip(),
            "query": query
        }
        
        if query.lower() in ["summary", "brief"]:
            lines = text.strip().split("\n")
            result["summary"] = " ".join(lines[:3])
        
        return result
        
    except Exception as e:
        return {
            "error": f"Failed to process image: {str(e)}",
            "image_input": str(image_input)
        }


def analyze_document_image(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze document-style images (certificates, transcripts, IDs).
    """
    image_input = arguments.get("image", "")
    doc_type = arguments.get("document_type", "generic")  # transcript, certificate, id
    
    if not HAS_OCR:
        return {
            "error": "Image processing libraries not installed.",
            "requires": ["Pillow", "pytesseract"]
        }
    
    try:
        if image_input.startswith("data:image"):
            header, data = image_input.split(",")
            image_bytes = base64.b64decode(data)
            img = Image.open(io.BytesIO(image_bytes))
        else:
            path = Path(image_input)
            if not path.exists():
                return {"error": f"Image not found: {image_input}"}
            img = Image.open(path)
        
        text = pytesseract.image_to_string(img)
        
        # Parse based on document type
        if doc_type == "transcript":
            return {
                "document_type": "academic_transcript",
                "extracted_text": text,
                "found_grades": "grade" in text.lower() or "gpa" in text.lower(),
                "found_courses": "course" in text.lower() or "subject" in text.lower()
            }
        elif doc_type == "certificate":
            return {
                "document_type": "certificate",
                "extracted_text": text,
                "found_name": "name" in text.lower(),
                "found_date": any(word in text for word in ["2023", "2024", "2025", "2026"])
            }
        elif doc_type == "id":
            return {
                "document_type": "identification",
                "extracted_text": text,
                "found_id_number": any(c.isdigit() for c in text if len(c) > 5),
                "found_name": any(word in text.lower() for word in ["name", "นาม"])
            }
        else:
            return {
                "document_type": "generic",
                "extracted_text": text
            }
            
    except Exception as e:
        return {
            "error": f"Document analysis failed: {str(e)}",
            "document_type": doc_type
        }
