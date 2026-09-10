// Minimal service worker. Its only job is to exist with a fetch handler, which
// is what Android needs before it will treat this as a real installed app.
//
// It deliberately does NOT cache anything. A Streamlit page is rendered on the
// server and streamed down a live connection, so a cached shell would just show
// a frozen screen with no data, and a cached bundle would go stale the moment
// the app is upgraded. Everything goes straight to the network.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* network only, on purpose */ });
