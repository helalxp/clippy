// Configuration for API endpoints
// If VITE_API_URL is set (e.g. in production), use it.
// Otherwise, default to empty string which means relative paths (proxied in dev).

export const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const getApiUrl = (path) => {
    if (path.startsWith('http')) return path;
    // Ensure path starts with / if not present
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    const runtimeBase = typeof window !== 'undefined' && window.__CLIPPY_API_BASE_URL__
        ? window.__CLIPPY_API_BASE_URL__
        : API_BASE_URL;
    const url = `${runtimeBase}${normalizedPath}`;
    // Browser media elements cannot attach X-Clippy-Token headers. Scope only
    // local static-media URLs with the current desktop session token instead.
    const mediaPath = normalizedPath.split('?')[0];
    const isMedia = /^\/(videos|thumbnails|reference-templates-media)(\/|$)/.test(mediaPath);
    const sessionToken = typeof window !== 'undefined' ? window.__CLIPPY_API_TOKEN__ : '';
    if (isMedia && sessionToken) {
        const mediaUrl = new URL(url, window.location.href);
        mediaUrl.searchParams.set('token', sessionToken);
        return mediaUrl.toString();
    }
    return url;
};
