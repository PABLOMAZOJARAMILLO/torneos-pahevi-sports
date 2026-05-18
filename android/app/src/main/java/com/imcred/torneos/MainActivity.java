package com.imcred.torneos;

import android.content.ContentValues;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.widget.Toast;

import com.getcapacitor.BridgeActivity;

import java.io.OutputStream;

public class MainActivity extends BridgeActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            if (url != null && url.startsWith("data:image/png;base64,")) {
                guardarImagenBase64(url, "");
            }
        });

        getBridge().getWebView().addJavascriptInterface(new AndroidDownloader(), "AndroidDownloader");
    }

    private void guardarImagenBase64(String dataUrl, String nombreArchivo) {
        try {
            String base64 = dataUrl.substring(dataUrl.indexOf(",") + 1);
            byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
            String nombre = limpiarNombre(nombreArchivo);
            if (nombre.isEmpty()) {
                nombre = "programacion_imcred_" + System.currentTimeMillis() + ".png";
            }

            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.DISPLAY_NAME, nombre);
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
            values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/TorneosIMCRED");

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

            Toast.makeText(this, "Imagen guardada en Fotos/TorneosIMCRED", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo descargar la imagen", Toast.LENGTH_LONG).show();
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

    public class AndroidDownloader {
        @JavascriptInterface
        public void guardarImagen(String dataUrl, String nombreArchivo) {
            runOnUiThread(() -> guardarImagenBase64(dataUrl, nombreArchivo));
        }
    }
}
