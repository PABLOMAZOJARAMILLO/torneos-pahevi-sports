# Supabase para base de datos e imagenes

Esta configuracion permite usar Supabase gratis para:

- Base de datos PostgreSQL.
- Escudos y fotos subidas desde la app.

## 1. Crear proyecto en Supabase

1. Entra a Supabase y crea un proyecto nuevo.
2. Guarda la clave de la base de datos.
3. En Project Settings > Database copia la cadena de conexion de PostgreSQL.

En Render se usara como:

```text
DATABASE_URL=postgresql://...
DATABASE_SSL_REQUIRE=true
```

## 2. Crear bucket para imagenes

1. En Supabase abre Storage.
2. Crea un bucket llamado:

```text
torneos-media
```

3. Marcalo como publico, porque los escudos y fotos se muestran en la app.

La URL publica queda con esta forma:

```text
https://PROJECT_REF.supabase.co/storage/v1/object/public/torneos-media
```

Esa URL va en Render como `SUPABASE_PUBLIC_MEDIA_URL`.

## 3. Activar S3 en Supabase Storage

1. En Supabase ve a Storage > Settings > S3.
2. Activa S3 protocol si aparece desactivado.
3. Genera un Access Key y Secret Key.
4. Copia tambien el endpoint y la region.

El endpoint normalmente tiene esta forma:

```text
https://PROJECT_REF.storage.supabase.co/storage/v1/s3
```

## 4. Variables de entorno en Render

En Render > tu Web Service > Environment agrega:

```text
DATABASE_URL=postgresql://...
DATABASE_SSL_REQUIRE=true
USE_SUPABASE_STORAGE=true
SUPABASE_STORAGE_BUCKET=torneos-media
SUPABASE_PUBLIC_MEDIA_URL=https://PROJECT_REF.supabase.co/storage/v1/object/public/torneos-media
SUPABASE_S3_ACCESS_KEY_ID=...
SUPABASE_S3_SECRET_ACCESS_KEY=...
SUPABASE_S3_ENDPOINT_URL=https://PROJECT_REF.storage.supabase.co/storage/v1/s3
SUPABASE_S3_REGION_NAME=...
```

No subas estas claves a GitHub.

## 5. Despues del deploy

1. En Render ejecuta migraciones:

```bash
python manage.py migrate
```

2. Crea o conserva tu usuario administrador.
3. Prueba subir un escudo desde Gestion del torneo.
4. Verifica que el archivo aparezca en Supabase Storage.

## Importante

Los archivos que ya estaban en `media/` no se migran solos a Supabase. Hay que volverlos a subir desde la app o hacer una migracion de archivos aparte.
