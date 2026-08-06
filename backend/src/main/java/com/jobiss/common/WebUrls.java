package com.jobiss.common;

import java.net.URI;

public final class WebUrls {

    private WebUrls() {
    }

    public static boolean isHttpUrl(String value) {
        if (value == null || value.isBlank()) {
            return false;
        }
        try {
            URI uri = URI.create(value.trim());
            String scheme = uri.getScheme();
            return uri.getHost() != null
                    && ("http".equalsIgnoreCase(scheme)
                    || "https".equalsIgnoreCase(scheme));
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }

    public static boolean isBlankOrHttpUrl(String value) {
        return value == null || value.isBlank() || isHttpUrl(value);
    }
}
