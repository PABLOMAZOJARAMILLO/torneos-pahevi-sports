import os
from urllib.parse import quote

from django.conf import settings
from django.core.files.storage import Storage
from storages.backends.s3 import S3Storage


class SupabaseMediaStorage(S3Storage):
    def url(self, name, parameters=None, expire=None, http_method=None):
        public_base = getattr(settings, "SUPABASE_PUBLIC_MEDIA_URL", "").rstrip("/")

        if public_base:
            clean_name = quote(str(name).lstrip("/"), safe="/")
            return f"{public_base}/{clean_name}"

        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)


class CloudinaryMediaStorage(Storage):
    raw_extensions = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
    }

    def _configure(self):
        import cloudinary

        cloudinary_url = getattr(settings, "CLOUDINARY_URL", "")

        if cloudinary_url:
            os.environ["CLOUDINARY_URL"] = cloudinary_url
            cloudinary.config(secure=True)
            return

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

    def _public_id(self, name):
        clean_name = str(name).replace("\\", "/").lstrip("/")
        if "." in clean_name and self._resource_type(clean_name) == "image":
            clean_name = clean_name.rsplit(".", 1)[0]
        return clean_name

    def _resource_type(self, name):
        extension = os.path.splitext(str(name).lower())[1]
        if extension in self.raw_extensions:
            return "raw"
        return "image"

    def _image_width(self, name):
        clean_name = str(name).replace("\\", "/").lower()
        if clean_name.startswith("jugadores/"):
            return 320
        if "/escudo" in clean_name:
            return 160
        if "/cuerpo_tecnico_" in clean_name:
            return 320
        return 900

    def _save(self, name, content):
        import cloudinary.uploader

        self._configure()
        public_id = self._public_id(name)
        resource_type = self._resource_type(name)
        upload_options = {
            "public_id": public_id,
            "resource_type": resource_type,
            "overwrite": True,
        }

        if resource_type == "image":
            upload_options["invalidate"] = True

        content.seek(0)
        cloudinary.uploader.upload(
            content,
            **upload_options,
        )
        return public_id

    def exists(self, name):
        return False

    def delete(self, name):
        if not name:
            return

        import cloudinary.uploader

        self._configure()
        cloudinary.uploader.destroy(
            self._public_id(name),
            resource_type=self._resource_type(name),
            invalidate=True,
        )

    def url(self, name):
        import cloudinary.utils

        self._configure()
        resource_type = self._resource_type(name)
        options = {
            "resource_type": resource_type,
            "secure": True,
        }
        if resource_type == "image":
            options["transformation"] = [
                {
                    "width": self._image_width(name),
                    "crop": "limit",
                    "quality": "auto",
                    "fetch_format": "auto",
                }
            ]
        return cloudinary.utils.cloudinary_url(
            str(name),
            **options,
        )[0]
