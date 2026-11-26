"""Reusable request validators for API endpoints."""

from fastapi import HTTPException, UploadFile, status


def validate_image_type(file_upload: UploadFile) -> None:
    """Validate if the provided MIME type is an allowed image type.

    Checks if the MIME type is in the predefined set of allowed image
    MIME types. This is used to ensure that only supported image formats
    are processed by the application.

    Args:
        file_upload: The uploaded file to validate.

    Raises:
        HTTPException: If the MIME type or file extension is not allowed.
    """
    from app.core.constant import ALLOWED_IMAGE_MIME_TYPES, ALLOWED_IMAGE_EXTENSIONS

    if file_upload.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{file_upload.content_type}' not allowed. Supported types: {allowed}",
        )
    elif not any(
        file_upload.filename.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS
    ):
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension not allowed. Supported extensions: {allowed}",
        )
