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
        if "." in clean_name:
            clean_name = clean_name.rsplit(".", 1)[0]
        return clean_name

    def _save(self, name, content):
        import cloudinary.uploader

        self._configure()
        public_id = self._public_id(name)
        content.seek(0)
        cloudinary.uploader.upload(
            content,
            public_id=public_id,
            resource_type="image",
            overwrite=True,
            invalidate=True,
        )
        return public_id

    def exists(self, name):
        return False

    def url(self, name):
        import cloudinary.utils

        self._configure()
        return cloudinary.utils.cloudinary_url(
            str(name),
            resource_type="image",
            secure=True,
        )[0]
