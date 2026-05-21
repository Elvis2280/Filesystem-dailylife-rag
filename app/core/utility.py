import re

def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a given name."""
    name = name.strip().lower()
    name = re.sub(r'[^a-z0-9]+', '-', name) # Replace non-alphanumeric characters with hyphens
    return name.strip('-') # Remove leading/trailing hyphens

def error_response(message: str, status_code: int = 400, details: dict = None) -> dict:
    """Utility function to create a standardized error response."""
    return {
        "error": {
            "status": "error",
            "code": status_code,
            "details": details or {},
            "message": message
        }
    }

def success_response(data: dict, status_code: int = 200, message: str = None) -> dict:
    """Utility function to create a standardized success response."""
    return {
        "status": "success",
        "code": status_code,
        "data": data,
        "message": message
    }