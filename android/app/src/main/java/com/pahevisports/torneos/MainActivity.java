package com.pahevisports.torneos;

import android.app.DownloadManager;
import android.content.Context;
import android.content.ContentValues;
import android.net.Uri;
import android.os.Environment;
import android.os.Bundle;
import android.os.Build;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.widget.Toast;

import com.getcapacitor.BridgeActivity;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

public class MainActivity extends BridgeActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        getBridge().getWebView().clearCache(true);
        getBridge().getWebView().getSettings().setCacheMode(WebSettings.LOAD_NO_CACHE);
        getBridge().getWebView().getSettings().setSupportZoom(true);
        getBridge().getWebView().getSettings().setBuiltInZoomControls(true);
        getBridge().getWebView().getSettings().setDisplayZoomControls(false);

        getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            if (url != null && url.startsWith("data:image/png;base64,")) {
                guardarImagenBase64(url, "");
                return;
            }
            descargarArchivo(url, userAgent, contentDisposition, mimetype);
        });

        getBridge().getWebView().addJavascriptInterface(new AndroidDownloader(), "AndroidDownloader");
    }

    private void guardarImagenBase64(String dataUrl, String nombreArchivo) {
        try {
            String base64 = dataUrl.substring(dataUrl.indexOf(",") + 1);
            byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
            String nombre = limpiarNombre(nombreArchivo);
            if (nombre.isEmpty()) {
                nombre = "programacion_pahevi_sports_" + System.currentTimeMillis() + ".png";
            }

            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, nombre);
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
            values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/TorneosPaheviSports");

            Uri uri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
            if (uri == null) {
                Toast.makeText(this, "No se pudo guardar la imagen", Toast.LENGTH_LONG).show();
                return;
            }

            try (OutputStream output = getContentResolver().openOutputStream(uri)) {
                if (output != null) {
                    output.write(bytes);
                }
            }

            Toast.makeText(this, "Imagen guardada en Fotos/TorneosPaheviSports", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo descargar la imagen", Toast.LENGTH_LONG).show();
        }
    }

    private void guardarArchivoBase64(String dataUrl, String nombreArchivo, String mimetype) {
        try {
            String base64 = dataUrl.substring(dataUrl.indexOf(",") + 1);
            byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
            String nombre = limpiarNombreDescarga(nombreArchivo, mimetype);
            String tipoArchivo = mimetype == null || mimetype.trim().isEmpty()
                ? (nombre.toLowerCase().endsWith(".zip") ? "application/zip" : "application/pdf")
                : mimetype;

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, nombre);
                values.put(MediaStore.MediaColumns.MIME_TYPE, tipoArchivo);
                values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/TorneosPaheviSports");

                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (uri == null) {
                    Toast.makeText(this, "No se pudo guardar el archivo", Toast.LENGTH_LONG).show();
                    return;
                }

                try (OutputStream output = getContentResolver().openOutputStream(uri)) {
                    if (output != null) {
                        output.write(bytes);
                    }
                }
            } else {
                File carpeta = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "TorneosPaheviSports");
                if (!carpeta.exists() && !carpeta.mkdirs()) {
                    Toast.makeText(this, "No se pudo crear la carpeta de descarga", Toast.LENGTH_LONG).show();
                    return;
                }
                File archivo = new File(carpeta, nombre);
                try (FileOutputStream output = new FileOutputStream(archivo)) {
                    output.write(bytes);
                }
            }

            Toast.makeText(this, "Archivo guardado en Descargas/TorneosPaheviSports", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo descargar el archivo", Toast.LENGTH_LONG).show();
        }
    }

    private String limpiarNombre(String nombreArchivo) {
        if (nombreArchivo == null) {
            return "";
        }

        String nombre = nombreArchivo.trim().replaceAll("[\\\\/:*?\"<>|]", "_");
        if (nombre.isEmpty()) {
            return "";
        }

        return nombre.toLowerCase().endsWith(".png") ? nombre : nombre + ".png";
    }

    private void descargarArchivo(String url, String userAgent, String contentDisposition, String mimetype) {
        try {
            if (url == null || url.trim().isEmpty()) {
                Toast.makeText(this, "No se pudo iniciar la descarga", Toast.LENGTH_LONG).show();
                return;
            }

            String nombre = URLUtil.guessFileName(url, contentDisposition, mimetype);
            nombre = limpiarNombreDescarga(nombre, mimetype);
            String tipoArchivo = mimetype == null || mimetype.trim().isEmpty()
                ? (nombre.toLowerCase().endsWith(".zip") ? "application/zip" : "application/pdf")
                : mimetype;

            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
            request.setMimeType(tipoArchivo);
            request.addRequestHeader("User-Agent", userAgent);

            String cookies = CookieManager.getInstance().getCookie(url);
            if (cookies != null) {
                request.addRequestHeader("Cookie", cookies);
            }

            request.setTitle(nombre);
            request.setDescription("Descargando planilla");
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, nombre);

            DownloadManager manager = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (manager == null) {
                Toast.makeText(this, "No se pudo acceder al gestor de descargas", Toast.LENGTH_LONG).show();
                return;
            }

            manager.enqueue(request);
            Toast.makeText(this, "Descarga iniciada en Descargas", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo descargar el archivo", Toast.LENGTH_LONG).show();
        }
    }

    private String limpiarNombreDescarga(String nombreArchivo, String mimetype) {
        String nombre = nombreArchivo == null ? "" : nombreArchivo.trim().replaceAll("[\\\\/:*?\"<>|]", "_");
        if (nombre.isEmpty()) {
            nombre = "planilla_pahevi_sports_" + System.currentTimeMillis();
        }

        String nombreMinuscula = nombre.toLowerCase();
        if (nombreMinuscula.endsWith(".pdf") || nombreMinuscula.endsWith(".zip")) {
            return nombre;
        }
        if ("application/zip".equalsIgnoreCase(mimetype)) {
            return nombre + ".zip";
        }
        return nombre + ".pdf";
    }

    public class AndroidDownloader {
        @JavascriptInterface
        public void guardarImagen(String dataUrl, String nombreArchivo) {
            runOnUiThread(() -> guardarImagenBase64(dataUrl, nombreArchivo));
        }

        @JavascriptInterface
        public void guardarArchivo(String dataUrl, String nombreArchivo, String mimetype) {
            runOnUiThread(() -> guardarArchivoBase64(dataUrl, nombreArchivo, mimetype));
        }

        @JavascriptInterface
        public void descargarUrl(String url, String nombreArchivo, String mimetype) {
            runOnUiThread(() -> descargarArchivo(url, getBridge().getWebView().getSettings().getUserAgentString(), "attachment; filename=\"" + nombreArchivo + "\"", mimetype));
        }
    }
}
