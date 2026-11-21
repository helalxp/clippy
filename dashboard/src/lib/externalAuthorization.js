export function openAuthorizationPlaceholder() {
  const opened = window.open('about:blank', '_blank');
  if (!opened) {
    throw new Error('Your browser blocked the authorization window.');
  }

  try {
    // Open synchronously from the user gesture, then sever opener before any
    // external provider page is navigated into this browsing context.
    opened.opener = null;
    return opened;
  } catch {
    try { opened.close(); } catch (_) { /* best effort */ }
    throw new Error('Clippy could not secure the authorization window.');
  }
}

export function navigateAuthorizationWindow(opened, url) {
  if (!opened || opened.closed) {
    throw new Error('The authorization window is no longer available. Open it again.');
  }
  try {
    opened.opener = null;
    opened.location.replace(url);
    return opened;
  } catch {
    try { opened.close(); } catch (_) { /* best effort */ }
    throw new Error('Clippy could not open the provider authorization page.');
  }
}
